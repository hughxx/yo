using System;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows.Forms;
using Extensibility;
using Microsoft.Office.Core;
using OutlookEmailForwarder.Forms;
using OutlookEmailForwarder.Models;
using OutlookEmailForwarder.Services;
using Outlook = Microsoft.Office.Interop.Outlook;

namespace OutlookEmailForwarder
{
    [ComVisible(true)]
    [Guid("A3F2B7C1-8D4E-4F5A-9B6C-1E2D3F4A5B6C")]
    [ProgId("OutlookEmailForwarder.AddinModule")]
    public class AddinModule : IDTExtensibility2, IRibbonExtensibility
    {
        private Outlook.Application _outlookApp;
        private Timer _scanTimer;
        private EmailScanner _scanner;
        private ApiClient _apiClient;
        private ProcessedTracker _tracker;
        private bool _isScanning;
        private static readonly object _scanLock = new object();

        #region IDTExtensibility2

        public void OnConnection(object application, ext_ConnectMode connectMode,
            object addInInst, ref Array custom)
        {
            _outlookApp = (Outlook.Application)application;
            if (connectMode != ext_ConnectMode.ext_cm_Startup)
                InitializeAddin();
        }

        public void OnStartupComplete(ref Array custom)
        {
            InitializeAddin();
        }

        public void OnDisconnection(ext_DisconnectMode removeMode, ref Array custom)
        {
            Cleanup();
        }

        public void OnAddInsUpdate(ref Array custom) { }
        public void OnBeginShutdown(ref Array custom) { }

        #endregion

        #region IRibbonExtensibility

        public string GetCustomUI(string ribbonID)
        {
            return @"<?xml version=""1.0"" encoding=""UTF-8""?>
<customUI xmlns=""http://schemas.microsoft.com/office/2009/07/customui"">
  <ribbon>
    <tabs>
      <tab idMso=""TabMail"">
        <group id=""CloudViewGroup"" label=""云见"">
          <button id=""btnMain""
                  label=""云见小助手""
                  screentip=""打开云见小助手面板""
                  size=""large""
                  imageMso=""ContactPictureMenu""
                  onAction=""OnMainClick""/>
        </group>
      </tab>
    </tabs>
  </ribbon>
</customUI>";
        }

        public void OnMainClick(IRibbonControl control)
        {
            try
            {
                using (var form = new MainForm(_outlookApp, RunScanWithLogAsync, _tracker))
                {
                    form.ShowDialog();
                    // 面板关闭后重新加载配置（用户可能改了）
                    ReloadConfig();
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"打开云见小助手失败：{ex.Message}", "错误",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        #endregion

        #region 核心逻辑

        private void InitializeAddin()
        {
            try
            {
                var config = ConfigManager.Load();
                _scanner = new EmailScanner();
                _tracker = new ProcessedTracker();
                _apiClient = new ApiClient(config.BackendUrl);

                _scanTimer = new Timer();
                _scanTimer.Interval = config.ScanIntervalMinutes * 60 * 1000;
                _scanTimer.Tick += (s, e) => { _ = RunScanWithLogAsync(null); };
                _scanTimer.Start();

                // 首次启动延迟5秒后静默扫描
                var startupTimer = new Timer { Interval = 5000 };
                startupTimer.Tick += (s, e) =>
                {
                    startupTimer.Stop();
                    startupTimer.Dispose();
                    _ = RunScanWithLogAsync(null);
                };
                startupTimer.Start();
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"[CloudView] Init error: {ex}");
            }
        }

        private void ReloadConfig()
        {
            ConfigManager.Reload();
            var config = ConfigManager.Load();
            _apiClient?.UpdateBaseUrl(config.BackendUrl);
            if (_scanTimer != null)
                _scanTimer.Interval = config.ScanIntervalMinutes * 60 * 1000;
        }

        /// <summary>
        /// 带日志回调的扫描，供MainForm调用；log为null时静默运行
        /// </summary>
        private async Task<ScanResult> RunScanWithLogAsync(Action<string> log)
        {
            var result = new ScanResult();

            lock (_scanLock)
            {
                if (_isScanning)
                {
                    log?.Invoke("上一次扫描尚未完成，请稍后再试。");
                    return result;
                }
                _isScanning = true;
            }

            try
            {
                var config = ConfigManager.Load();

                if (config.Rules.Count == 0)
                {
                    log?.Invoke("未配置任何转发规则。");
                    return result;
                }

                log?.Invoke("正在扫描收件箱...");
                var matchedEmails = _scanner.ScanInbox(_outlookApp, config.Rules, _tracker, log,
                    config.ScanFolders);
                result.MatchedCount = matchedEmails.Count;

                if (matchedEmails.Count == 0)
                {
                    log?.Invoke("没有发现新的匹配邮件。");
                    return result;
                }

                log?.Invoke($"发现 {matchedEmails.Count} 封匹配邮件，开始发送...");

                for (int i = 0; i < matchedEmails.Count; i++)
                {
                    var matched = matchedEmails[i];
                    try
                    {
                        log?.Invoke($"[{i + 1}/{matchedEmails.Count}] 发送：{matched.Mail.Subject}");

                        var payload = _scanner.ConvertToPayload(matched.Mail, matched.RuleName, config);
                        var apiResult = await _apiClient.SendEmailAsync(payload);

                        if (apiResult.Success)
                        {
                            _tracker.MarkProcessed(matched.Mail.EntryID, matched.Mail.ReceivedTime);
                            result.SuccessCount++;
                            log?.Invoke($"  -> 成功（{apiResult.Message}）");
                        }
                        else
                        {
                            result.FailedCount++;
                            log?.Invoke($"  -> 失败：{apiResult.Message}");
                            await _apiClient.ReportErrorAsync(new ErrorReport
                            {
                                ErrorMessage = apiResult.Message,
                                OccurredAt = DateTime.Now.ToString("o"),
                                EmailId = matched.Mail.EntryID,
                                ExtraInfo = config.ExtraInfo
                            });
                        }
                    }
                    catch (Exception ex)
                    {
                        result.FailedCount++;
                        log?.Invoke($"  -> 异常：{ex.Message}");
                        await _apiClient.ReportErrorAsync(new ErrorReport
                        {
                            ErrorMessage = ex.Message,
                            StackTrace = ex.StackTrace,
                            OccurredAt = DateTime.Now.ToString("o"),
                            EmailId = matched.Mail?.EntryID,
                            ExtraInfo = config.ExtraInfo
                        });
                    }
                    finally
                    {
                        if (matched.Mail != null)
                            Marshal.ReleaseComObject(matched.Mail);
                    }
                }

                _tracker.Cleanup();
                _tracker.SaveToDisk();
                // 单次文件夹扫完后 Enabled 已被置 false，持久化配置
                ConfigManager.Save(config);
            }
            catch (Exception ex)
            {
                log?.Invoke($"扫描异常：{ex.Message}");
                System.Diagnostics.Debug.WriteLine($"[CloudView] Scan error: {ex}");
            }
            finally
            {
                _isScanning = false;
            }

            return result;
        }

        private void Cleanup()
        {
            _scanTimer?.Stop();
            _scanTimer?.Dispose();
            _apiClient?.Dispose();
            _tracker?.SaveToDisk();
            if (_outlookApp != null)
            {
                Marshal.ReleaseComObject(_outlookApp);
                _outlookApp = null;
            }
        }

        #endregion

        #region COM注册

        [ComRegisterFunction]
        public static void Register(Type type)
        {
            string keyName = $@"Software\Microsoft\Office\Outlook\Addins\{type.FullName}";
            using (var key = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(keyName))
            {
                key.SetValue("FriendlyName", "云见小助手");
                key.SetValue("Description", "根据规则自动转发邮件内容到后端系统");
                key.SetValue("LoadBehavior", 3);
            }
        }

        [ComUnregisterFunction]
        public static void Unregister(Type type)
        {
            string keyName = $@"Software\Microsoft\Office\Outlook\Addins\{type.FullName}";
            Microsoft.Win32.Registry.CurrentUser.DeleteSubKey(keyName, false);
        }

        #endregion
    }
}
