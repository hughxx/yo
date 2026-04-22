using System;
using System.Collections.Generic;
using System.Drawing;
using System.Runtime.InteropServices;
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
        private Button btnScan;
        private Button btnConfig;
        private Button btnClearCache;
        private Button btnRefresh;
        private ProgressBar progressBar;
        private DataGridView dgvEmails;
        private Button btnFirst, btnPrev, btnNext, btnLast;
        private Label lblPageInfo;
        private Label lblTotal;

        private readonly Outlook.Application _outlookApp;
        private readonly Func<Action<string>, Task<ScanResult>> _scanFunc;
        private readonly ProcessedTracker _tracker;

        private readonly List<EmailRow> _allEmails = new List<EmailRow>();
        private int _currentPage = 1;
        private const int PageSize = 30;

        public MainForm(Outlook.Application outlookApp,
            Func<Action<string>, Task<ScanResult>> scanFunc,
            ProcessedTracker tracker)
        {
            _outlookApp = outlookApp;
            _scanFunc = scanFunc;
            _tracker = tracker;
            InitializeComponents();
            _ = LoadEmailsAsync();
        }

        private void InitializeComponents()
        {
            this.Text = "云见小助手";
            this.Size = new Size(900, 600);
            this.MinimumSize = new Size(700, 480);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.Font = new Font("Microsoft YaHei UI", 9F);

            // ===== 顶部工具栏 =====
            var toolbar = new Panel
            {
                Dock = DockStyle.Top,
                Height = 46,
                BackColor = Color.FromArgb(248, 248, 248),
                Padding = new Padding(8, 8, 8, 6)
            };

            lblStatus = new Label
            {
                Text = "就绪",
                Location = new Point(10, 13),
                AutoSize = true,
                Font = new Font("Microsoft YaHei UI", 10F, FontStyle.Bold),
                ForeColor = Color.Green
            };

            btnScan      = MakeBtn("立即扫描", 130, Color.FromArgb(0, 120, 212));
            btnConfig    = MakeBtn("配置规则", 238, Color.FromArgb(80, 80, 80));
            btnClearCache = MakeBtn("清空缓存", 336, Color.FromArgb(180, 60, 60));
            btnRefresh   = MakeBtn("刷新邮件", 444, Color.FromArgb(0, 140, 100));

            btnScan.Location      = new Point(130, 9);
            btnConfig.Location    = new Point(238, 9);
            btnClearCache.Location = new Point(336, 9);
            btnRefresh.Location   = new Point(444, 9);

            btnScan.Click      += BtnScan_Click;
            btnConfig.Click    += BtnConfig_Click;
            btnClearCache.Click += BtnClearCache_Click;
            btnRefresh.Click   += async (s, e) => await LoadEmailsAsync();

            toolbar.Controls.AddRange(new Control[] { lblStatus, btnScan, btnConfig, btnClearCache, btnRefresh });

            // ===== 进度条 =====
            progressBar = new ProgressBar
            {
                Dock = DockStyle.Top,
                Height = 4,
                Style = ProgressBarStyle.Marquee,
                MarqueeAnimationSpeed = 30,
                Visible = false
            };

            // ===== 分页栏 =====
            var paginPanel = new Panel
            {
                Dock = DockStyle.Bottom,
                Height = 34,
                BackColor = Color.FromArgb(248, 248, 248)
            };

            btnFirst = PagBtn("«", 8);
            btnPrev  = PagBtn("‹", 42);
            lblPageInfo = new Label { Size = new Size(110, 22), Location = new Point(78, 6), TextAlign = ContentAlignment.MiddleCenter, Text = "第 1 / 1 页" };
            btnNext  = PagBtn("›", 192);
            btnLast  = PagBtn("»", 226);
            lblTotal = new Label { Size = new Size(120, 22), Location = new Point(268, 6), ForeColor = Color.Gray, Text = "共 0 封", TextAlign = ContentAlignment.MiddleLeft };

            btnFirst.Click += (s, e) => { _currentPage = 1; RefreshTable(); };
            btnPrev.Click  += (s, e) => { if (_currentPage > 1) { _currentPage--; RefreshTable(); } };
            btnNext.Click  += (s, e) => { if (_currentPage < TotalPages()) { _currentPage++; RefreshTable(); } };
            btnLast.Click  += (s, e) => { _currentPage = TotalPages(); RefreshTable(); };

            paginPanel.Controls.AddRange(new Control[] { btnFirst, btnPrev, lblPageInfo, btnNext, btnLast, lblTotal });

            // ===== 邮件表格 =====
            dgvEmails = new DataGridView
            {
                Dock = DockStyle.Fill,
                ReadOnly = true,
                AllowUserToAddRows = false,
                AllowUserToDeleteRows = false,
                AllowUserToResizeRows = false,
                SelectionMode = DataGridViewSelectionMode.FullRowSelect,
                MultiSelect = false,
                RowHeadersVisible = false,
                ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing,
                ColumnHeadersHeight = 26,
                RowTemplate = { Height = 24 },
                BackgroundColor = Color.White,
                BorderStyle = BorderStyle.None,
                GridColor = Color.FromArgb(225, 225, 225),
                Font = new Font("Microsoft YaHei UI", 9F),
                DefaultCellStyle = { SelectionBackColor = Color.FromArgb(0, 120, 212), SelectionForeColor = Color.White }
            };
            dgvEmails.ColumnHeadersDefaultCellStyle.Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Bold);
            dgvEmails.EnableHeadersVisualStyles = false;
            dgvEmails.ColumnHeadersDefaultCellStyle.BackColor = Color.FromArgb(240, 240, 240);

            dgvEmails.Columns.Add(new DataGridViewTextBoxColumn { Name = "colNum",    HeaderText = "#",    Width = 45, SortMode = DataGridViewColumnSortMode.NotSortable });
            dgvEmails.Columns.Add(new DataGridViewTextBoxColumn { Name = "colTime",   HeaderText = "时间",  Width = 130, SortMode = DataGridViewColumnSortMode.NotSortable });
            dgvEmails.Columns.Add(new DataGridViewTextBoxColumn { Name = "colSender", HeaderText = "发件人", Width = 160, SortMode = DataGridViewColumnSortMode.NotSortable });
            dgvEmails.Columns.Add(new DataGridViewTextBoxColumn { Name = "colSubject",HeaderText = "主题",  AutoSizeMode = DataGridViewAutoSizeColumnMode.Fill, SortMode = DataGridViewColumnSortMode.NotSortable });
            dgvEmails.Columns.Add(new DataGridViewTextBoxColumn { Name = "colFolder", HeaderText = "文件夹", Width = 130, SortMode = DataGridViewColumnSortMode.NotSortable });

            // 控件添加顺序决定 Dock 布局（Fill 必须在 Top/Bottom 后加入）
            this.Controls.Add(dgvEmails);
            this.Controls.Add(paginPanel);
            this.Controls.Add(progressBar);
            this.Controls.Add(toolbar);
        }

        private static Button MakeBtn(string text, int x, Color color)
        {
            var b = new Button
            {
                Text = text,
                Location = new Point(x, 9),
                Size = new Size(94, 28),
                FlatStyle = FlatStyle.Flat,
                BackColor = color,
                ForeColor = Color.White,
                Cursor = Cursors.Hand
            };
            b.FlatAppearance.BorderSize = 0;
            return b;
        }

        private static Button PagBtn(string text, int x)
        {
            var b = new Button
            {
                Text = text,
                Location = new Point(x, 5),
                Size = new Size(30, 24),
                FlatStyle = FlatStyle.Flat
            };
            b.FlatAppearance.BorderColor = Color.LightGray;
            return b;
        }

        private int TotalPages() => Math.Max(1, (_allEmails.Count + PageSize - 1) / PageSize);

        private void RefreshTable()
        {
            dgvEmails.Rows.Clear();
            int start = (_currentPage - 1) * PageSize;
            int end   = Math.Min(start + PageSize, _allEmails.Count);
            for (int i = start; i < end; i++)
            {
                var r = _allEmails[i];
                dgvEmails.Rows.Add(i + 1, r.ReceivedTime.ToString("yyyy-MM-dd HH:mm"), r.SenderName, r.Subject, r.Folder);
            }
            int total = TotalPages();
            lblPageInfo.Text = $"第 {_currentPage} / {total} 页";
            lblTotal.Text    = $"共 {_allEmails.Count} 封";
            btnFirst.Enabled = btnPrev.Enabled = _currentPage > 1;
            btnNext.Enabled  = btnLast.Enabled  = _currentPage < total;
        }

        // 在 UI 线程上做 COM 调用，Brief Yield 让进度条先渲染
        private async Task LoadEmailsAsync()
        {
            progressBar.Visible = true;
            btnRefresh.Enabled = false;
            SetStatus("加载中...", Color.Orange);

            try
            {
                await Task.Delay(20); // 让进度条渲染
                _allEmails.Clear();
                CollectEmailsFromOutlook();
                _currentPage = 1;
                RefreshTable();
                SetStatus("就绪", Color.Green);
            }
            catch (Exception ex)
            {
                SetStatus($"加载失败：{ex.Message}", Color.Red);
            }
            finally
            {
                progressBar.Visible = false;
                btnRefresh.Enabled = true;
            }
        }

        private void CollectEmailsFromOutlook()
        {
            Outlook.NameSpace ns = null;
            Outlook.Stores stores = null;
            try
            {
                ns = _outlookApp.GetNamespace("MAPI");
                stores = ns.Stores;
                for (int s = 1; s <= stores.Count; s++)
                {
                    Outlook.Store store = null;
                    try { store = stores[s]; } catch { continue; }

                    string storeLabel = $"账户{s}";
                    try { storeLabel = store.DisplayName; } catch { }

                    Outlook.MAPIFolder inbox = null;
                    Outlook.Items items = null;
                    try
                    {
                        inbox = store.GetDefaultFolder(Outlook.OlDefaultFolders.olFolderInbox);
                        items = inbox.Items;
                        items.Sort("[ReceivedTime]", true); // 最新在前

                        int limit = Math.Min(items.Count, 300);
                        object cur = items.GetFirst();
                        int count = 0;
                        while (cur != null && count < limit)
                        {
                            var mail = cur as Outlook.MailItem;
                            if (mail != null)
                            {
                                _allEmails.Add(new EmailRow
                                {
                                    Subject      = mail.Subject ?? "",
                                    SenderName   = mail.SenderName ?? "",
                                    ReceivedTime = mail.ReceivedTime,
                                    Folder       = storeLabel
                                });
                                count++;
                            }
                            try { Marshal.ReleaseComObject(cur); } catch { }
                            cur = items.GetNext();
                        }
                        if (cur != null) try { Marshal.ReleaseComObject(cur); } catch { }
                    }
                    catch { }
                    finally
                    {
                        if (items != null) try { Marshal.ReleaseComObject(items); } catch { }
                        if (inbox != null) try { Marshal.ReleaseComObject(inbox); } catch { }
                        try { Marshal.ReleaseComObject(store); } catch { }
                    }
                }
            }
            catch { }
            finally
            {
                if (stores != null) try { Marshal.ReleaseComObject(stores); } catch { }
            }

            // 多账户合并后按时间降序
            _allEmails.Sort((a, b) => b.ReceivedTime.CompareTo(a.ReceivedTime));
        }

        private void SetStatus(string text, Color color)
        {
            if (lblStatus.InvokeRequired)
                lblStatus.Invoke(new Action(() => { lblStatus.Text = text; lblStatus.ForeColor = color; }));
            else
            { lblStatus.Text = text; lblStatus.ForeColor = color; }
        }

        private async void BtnScan_Click(object sender, EventArgs e)
        {
            btnScan.Enabled = false;
            btnScan.Text = "扫描中...";
            progressBar.Visible = true;
            SetStatus("扫描中...", Color.Orange);

            try
            {
                var result = await _scanFunc(msg => SetStatus(msg, Color.DarkCyan));
                string summary = result.MatchedCount == 0
                    ? "扫描完成，无新邮件"
                    : $"完成：匹配 {result.MatchedCount} 封，成功 {result.SuccessCount}，失败 {result.FailedCount}";
                SetStatus(summary, result.FailedCount > 0 ? Color.Red : Color.Green);

                // 扫完刷新表格
                await LoadEmailsAsync();
            }
            catch (Exception ex)
            {
                SetStatus($"扫描出错：{ex.Message}", Color.Red);
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
            using (var form = new ConfigForm(_outlookApp))
            {
                if (form.ShowDialog(this) == DialogResult.OK)
                    SetStatus("配置已更新", Color.Green);
            }
        }

        private void BtnClearCache_Click(object sender, EventArgs e)
        {
            if (MessageBox.Show(
                $"当前缓存了 {_tracker.Count} 封已处理邮件记录。\n\n清空后下次扫描会重新提交所有匹配邮件（后端会自动去重）。\n\n确定清空？",
                "清空缓存", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            {
                _tracker.ClearAll();
                SetStatus("缓存已清空", Color.Green);
            }
        }

        private class EmailRow
        {
            public string Subject      { get; set; }
            public string SenderName   { get; set; }
            public DateTime ReceivedTime { get; set; }
            public string Folder       { get; set; }
        }
    }

    public class ScanResult
    {
        public int ScannedCount { get; set; }
        public int MatchedCount { get; set; }
        public int SuccessCount { get; set; }
        public int FailedCount  { get; set; }
    }
}
