using System;
using System.Drawing;
using System.Threading.Tasks;
using System.Windows.Forms;
using OutlookEmailForwarder.Models;
using OutlookEmailForwarder.Services;
using Outlook = Microsoft.Office.Interop.Outlook;

namespace OutlookEmailForwarder.Forms
{
    public class MainForm : Form
    {
        private Label lblStatus;
        private Label lblLastScan;
        private Label lblRuleCount;
        private Label lblCacheCount;
        private Button btnScan;
        private Button btnConfig;
        private Button btnClearCache;
        private TextBox txtLog;
        private ProgressBar progressBar;

        private readonly Outlook.Application _outlookApp;
        private readonly Func<Action<string>, Task<ScanResult>> _scanFunc;
        private readonly ProcessedTracker _tracker;

        public MainForm(Outlook.Application outlookApp,
            Func<Action<string>, Task<ScanResult>> scanFunc,
            ProcessedTracker tracker)
        {
            _outlookApp = outlookApp;
            _scanFunc = scanFunc;
            _tracker = tracker;
            InitializeComponents();
            RefreshStatus();
        }

        private void InitializeComponents()
        {
            this.Text = "云见小助手";
            this.Size = new Size(500, 500);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.Font = new Font("Microsoft YaHei UI", 9F);

            // ===== 状态区 =====
            var grpStatus = new GroupBox
            {
                Text = "运行状态",
                Location = new Point(15, 10),
                Size = new Size(455, 85)
            };

            lblStatus = new Label
            {
                Text = "就绪",
                Location = new Point(15, 22),
                AutoSize = true,
                ForeColor = Color.Green,
                Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold)
            };

            lblLastScan = new Label
            {
                Text = "上次扫描：--",
                Location = new Point(15, 48),
                AutoSize = true,
                ForeColor = Color.Gray
            };

            lblRuleCount = new Label
            {
                Text = "已配置规则：0 条",
                Location = new Point(200, 48),
                AutoSize = true,
                ForeColor = Color.Gray
            };

            lblCacheCount = new Label
            {
                Text = "已缓存：0 封",
                Location = new Point(370, 48),
                AutoSize = true,
                ForeColor = Color.Gray
            };

            grpStatus.Controls.AddRange(new Control[] { lblStatus, lblLastScan, lblRuleCount, lblCacheCount });

            // ===== 操作按钮 =====
            btnScan = new Button
            {
                Text = "立即扫描",
                Location = new Point(15, 105),
                Size = new Size(145, 42),
                Font = new Font("Microsoft YaHei UI", 11F),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(0, 120, 212),
                ForeColor = Color.White,
                Cursor = Cursors.Hand
            };
            btnScan.FlatAppearance.BorderSize = 0;
            btnScan.Click += BtnScan_Click;

            btnConfig = new Button
            {
                Text = "配置规则",
                Location = new Point(170, 105),
                Size = new Size(145, 42),
                Font = new Font("Microsoft YaHei UI", 11F),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(100, 100, 100),
                ForeColor = Color.White,
                Cursor = Cursors.Hand
            };
            btnConfig.FlatAppearance.BorderSize = 0;
            btnConfig.Click += BtnConfig_Click;

            btnClearCache = new Button
            {
                Text = "清空缓存",
                Location = new Point(325, 105),
                Size = new Size(145, 42),
                Font = new Font("Microsoft YaHei UI", 11F),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(180, 60, 60),
                ForeColor = Color.White,
                Cursor = Cursors.Hand
            };
            btnClearCache.FlatAppearance.BorderSize = 0;
            btnClearCache.Click += BtnClearCache_Click;

            // ===== 进度条 =====
            progressBar = new ProgressBar
            {
                Location = new Point(15, 158),
                Size = new Size(455, 6),
                Style = ProgressBarStyle.Marquee,
                MarqueeAnimationSpeed = 30,
                Visible = false
            };

            // ===== 日志区 =====
            var lblLog = new Label
            {
                Text = "扫描日志",
                Location = new Point(15, 172),
                AutoSize = true,
                ForeColor = Color.Gray
            };

            txtLog = new TextBox
            {
                Location = new Point(15, 192),
                Size = new Size(455, 260),
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                BackColor = Color.FromArgb(30, 30, 30),
                ForeColor = Color.FromArgb(200, 200, 200),
                Font = new Font("Consolas", 9F)
            };

            this.Controls.AddRange(new Control[] {
                grpStatus, btnScan, btnConfig, btnClearCache, progressBar, lblLog, txtLog
            });
        }

        private void RefreshStatus()
        {
            var config = ConfigManager.Load();
            int enabledCount = 0;
            foreach (var r in config.Rules)
                if (r.Enabled) enabledCount++;

            lblRuleCount.Text = $"规则：{enabledCount}/{config.Rules.Count} 条";
            lblCacheCount.Text = $"已缓存：{_tracker.Count} 封";

            if (enabledCount == 0)
            {
                lblStatus.Text = "未配置规则";
                lblStatus.ForeColor = Color.Orange;
            }
            else
            {
                lblStatus.Text = "运行中";
                lblStatus.ForeColor = Color.Green;
            }
        }

        private void AppendLog(string message)
        {
            if (txtLog.InvokeRequired)
            {
                txtLog.Invoke(new Action(() => AppendLog(message)));
                return;
            }
            string time = DateTime.Now.ToString("HH:mm:ss");
            txtLog.AppendText($"[{time}] {message}{Environment.NewLine}");
        }

        private async void BtnScan_Click(object sender, EventArgs e)
        {
            btnScan.Enabled = false;
            btnScan.Text = "扫描中...";
            progressBar.Visible = true;
            AppendLog("开始扫描收件箱...");

            try
            {
                var result = await _scanFunc(AppendLog);

                lblLastScan.Text = $"上次扫描：{DateTime.Now:HH:mm:ss}";
                RefreshStatus();

                if (result.MatchedCount == 0)
                {
                    AppendLog("扫描完成，没有新的匹配邮件。");
                }
                else
                {
                    AppendLog($"扫描完成！匹配 {result.MatchedCount} 封，" +
                              $"成功 {result.SuccessCount} 封，失败 {result.FailedCount} 封。");
                }

                if (result.FailedCount > 0)
                {
                    AppendLog($"有 {result.FailedCount} 封发送失败，将在下次扫描时重试。");
                }
            }
            catch (Exception ex)
            {
                AppendLog($"扫描出错：{ex.Message}");
            }
            finally
            {
                btnScan.Enabled = true;
                btnScan.Text = "立即扫描";
                progressBar.Visible = false;
            }
        }

        private void BtnConfig_Click(object sender, EventArgs e)
        {
            using (var form = new ConfigForm())
            {
                if (form.ShowDialog(this) == DialogResult.OK)
                {
                    ConfigManager.Reload();
                    RefreshStatus();
                    AppendLog("配置已更新。");
                }
            }
        }

        private void BtnClearCache_Click(object sender, EventArgs e)
        {
            if (MessageBox.Show(
                $"当前缓存了 {_tracker.Count} 封已处理邮件记录。\n\n" +
                "清空后下次扫描会重新提交所有匹配邮件（后端会自动去重，不会产生重复数据）。\n\n确定清空？",
                "清空缓存", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            {
                _tracker.ClearAll();
                RefreshStatus();
                AppendLog($"缓存已清空，下次扫描将重新提交所有匹配邮件。");
            }
        }
    }

    public class ScanResult
    {
        public int ScannedCount { get; set; }
        public int MatchedCount { get; set; }
        public int SuccessCount { get; set; }
        public int FailedCount { get; set; }
    }
}
