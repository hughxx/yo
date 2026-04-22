using System;
using System.Drawing;
using System.Linq;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using System.Collections.Generic;
using OutlookEmailForwarder.Models;
using OutlookEmailForwarder.Services;
using Outlook = Microsoft.Office.Interop.Outlook;

namespace OutlookEmailForwarder.Forms
{
    public class ConfigForm : Form
    {
        private TabControl tabControl;
        // 基本设置页
        private TextBox txtBackendUrl;
        private NumericUpDown numInterval;
        private Button btnTestConnection;
        // 用户信息页 - 工号（单框：输入+搜索+回填）
        private ComboBox cboEmployee;
        private string _selectedSAMAccountName = "";
        private List<EmployeeInfo> _employeeSearchResults = new List<EmployeeInfo>();
        // 用户信息页 - 产品
        private ComboBox cboProduct;
        private Button btnLoadProducts;
        // 用户信息页 - 扩展配置
        private TextBox txtCustomJson;
        // 规则页
        private ListView lvRules;
        private Button btnAddRule;
        private Button btnEditRule;
        private Button btnDeleteRule;
        private Button btnToggleRule;
        // 底部按钮
        private Button btnSave;
        private Button btnCancel;

        private AppConfig _config;
        private readonly Outlook.Application _outlookApp;

        public ConfigForm(Outlook.Application outlookApp = null)
        {
            _outlookApp = outlookApp;
            _config = ConfigManager.Load();
            InitializeComponents();
            LoadConfigToUI();
        }

        private void InitializeComponents()
        {
            this.Text = "邮件转发助手 - 配置";
            this.Size = new Size(620, 520);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = false;
            this.Font = new Font("Microsoft YaHei UI", 9F);

            tabControl = new TabControl { Dock = DockStyle.None, Location = new Point(10, 10), Size = new Size(585, 420) };

            // ===== Tab 1: 基本设置 =====
            var tabBasic = new TabPage("基本设置");
            var lblUrl = new Label { Text = "后端地址：", Location = new Point(20, 30), AutoSize = true };
            txtBackendUrl = new TextBox { Location = new Point(120, 27), Size = new Size(350, 25) };
            btnTestConnection = new Button { Text = "测试连接", Location = new Point(480, 25), Size = new Size(80, 28) };
            btnTestConnection.Click += BtnTestConnection_Click;

            var lblInterval = new Label { Text = "扫描间隔(分钟)：", Location = new Point(20, 70), AutoSize = true };
            numInterval = new NumericUpDown { Location = new Point(150, 67), Size = new Size(80, 25), Minimum = 1, Maximum = 1440, Value = 5 };

            var grpInfo = new GroupBox { Text = "提示", Location = new Point(20, 110), Size = new Size(540, 60) };
            var lblTip = new Label
            {
                Text = "后端地址格式示例：http://192.168.1.100:5000\n扫描间隔：插件启动后每隔指定分钟扫描一次收件箱新邮件",
                Location = new Point(10, 18),
                AutoSize = true,
                ForeColor = Color.Gray
            };
            grpInfo.Controls.Add(lblTip);

            tabBasic.Controls.AddRange(new Control[] { lblUrl, txtBackendUrl, btnTestConnection, lblInterval, numInterval, grpInfo });

            // ===== Tab 2: 用户信息 =====
            var tabUser = new TabPage("用户信息");
            var panelUser = new Panel { Dock = DockStyle.Fill, AutoScroll = true, Padding = new Padding(0, 0, 4, 0) };

            // 工号：单框，输入后回车搜索，结果下拉选择后回填
            var lblEmpSearch = new Label { Text = "工号：", Location = new Point(20, 22), AutoSize = true };
            cboEmployee = new ComboBox
            {
                Location = new Point(75, 19),
                Size = new Size(485, 25),
                DropDownStyle = ComboBoxStyle.DropDown,
                AutoCompleteMode = AutoCompleteMode.None
            };
            cboEmployee.KeyDown += (s, e) => { if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; BtnSearchEmployee_Click(s, e); } };
            cboEmployee.SelectedIndexChanged += CboEmpResults_SelectedIndexChanged;

            // 产品分类
            var lblProduct = new Label { Text = "产品分类：", Location = new Point(20, 60), AutoSize = true };
            cboProduct = new ComboBox
            {
                Location = new Point(100, 57),
                Size = new Size(370, 25),
                DropDownStyle = ComboBoxStyle.DropDownList
            };
            btnLoadProducts = new Button { Text = "刷新", Location = new Point(478, 57), Size = new Size(50, 27) };
            btnLoadProducts.Click += BtnLoadProducts_Click;

            // 扩展配置
            var lblCustom = new Label { Text = "扩展配置(JSON)：", Location = new Point(20, 100), AutoSize = true };
            txtCustomJson = new TextBox
            {
                Location = new Point(20, 120),
                Size = new Size(540, 230),
                Multiline = true,
                ScrollBars = ScrollBars.Vertical,
                Font = new Font("Consolas", 9F)
            };
            var lblCustomTip = new Label
            {
                Text = "扩展配置用于向后端传递额外信息，请输入合法的JSON格式。",
                Location = new Point(20, 358),
                Size = new Size(540, 20),
                ForeColor = Color.Gray
            };

            panelUser.Controls.AddRange(new Control[] {
                lblEmpSearch, cboEmployee,
                lblProduct, cboProduct, btnLoadProducts,
                lblCustom, txtCustomJson, lblCustomTip
            });
            tabUser.Controls.Add(panelUser);

            // ===== Tab 3: 转发规则 =====
            var tabRules = new TabPage("转发规则");
            lvRules = new ListView
            {
                Location = new Point(20, 20),
                Size = new Size(540, 300),
                View = View.Details,
                FullRowSelect = true,
                GridLines = true,
                MultiSelect = false
            };
            lvRules.Columns.Add("启用", 50);
            lvRules.Columns.Add("规则名称", 120);
            lvRules.Columns.Add("关键词", 150);
            lvRules.Columns.Add("发件人", 120);
            lvRules.Columns.Add("逻辑", 60);

            btnAddRule = new Button { Text = "添加规则", Location = new Point(20, 330), Size = new Size(90, 30) };
            btnEditRule = new Button { Text = "编辑规则", Location = new Point(120, 330), Size = new Size(90, 30) };
            btnDeleteRule = new Button { Text = "删除规则", Location = new Point(220, 330), Size = new Size(90, 30) };
            btnToggleRule = new Button { Text = "启用/禁用", Location = new Point(320, 330), Size = new Size(90, 30) };

            btnAddRule.Click += BtnAddRule_Click;
            btnEditRule.Click += BtnEditRule_Click;
            btnDeleteRule.Click += BtnDeleteRule_Click;
            btnToggleRule.Click += BtnToggleRule_Click;

            tabRules.Controls.AddRange(new Control[] { lvRules, btnAddRule, btnEditRule, btnDeleteRule, btnToggleRule });

            tabControl.TabPages.AddRange(new[] { tabBasic, tabUser, tabRules });

            // ===== 底部按钮 =====
            btnSave = new Button { Text = "保存", Location = new Point(400, 440), Size = new Size(90, 32) };
            btnCancel = new Button { Text = "取消", Location = new Point(500, 440), Size = new Size(90, 32) };
            btnSave.Click += BtnSave_Click;
            btnCancel.Click += (s, e) => this.Close();

            this.Controls.AddRange(new Control[] { tabControl, btnSave, btnCancel });
        }

        private void LoadConfigToUI()
        {
            txtBackendUrl.Text = _config.BackendUrl;
            numInterval.Value = Math.Max(1, Math.Min(1440, _config.ScanIntervalMinutes));

            _selectedSAMAccountName = _config.ExtraInfo.EmployeeId;
            cboEmployee.Text = _selectedSAMAccountName;
            txtCustomJson.Text = _config.CustomJsonConfig;

            RefreshRuleList();
            _ = LoadProductsAsync(_config.ExtraInfo.ProductCategory);
        }

        private async System.Threading.Tasks.Task LoadProductsAsync(string selectedProduct)
        {
            btnLoadProducts.Enabled = false;
            btnLoadProducts.Text = "加载中";
            try
            {
                using (var client = new ApiClient(txtBackendUrl.Text.Trim()))
                {
                    var products = await client.GetProductsAsync();
                    if (cboProduct.IsDisposed) return;
                    cboProduct.Invoke(new Action(() =>
                    {
                        cboProduct.Items.Clear();
                        foreach (var p in products)
                            cboProduct.Items.Add(p);
                        if (!string.IsNullOrEmpty(selectedProduct))
                        {
                            int idx = cboProduct.Items.IndexOf(selectedProduct);
                            if (idx >= 0) cboProduct.SelectedIndex = idx;
                        }
                    }));
                }
            }
            catch { }
            finally
            {
                if (!btnLoadProducts.IsDisposed)
                    btnLoadProducts.Invoke(new Action(() => { btnLoadProducts.Enabled = true; btnLoadProducts.Text = "刷新"; }));
            }
        }

        private void RefreshRuleList()
        {
            lvRules.Items.Clear();
            foreach (var rule in _config.Rules)
            {
                var item = new ListViewItem(rule.Enabled ? "✓" : "✗");
                item.SubItems.Add(rule.Name);
                item.SubItems.Add(string.Join(", ", rule.Keywords));
                item.SubItems.Add(string.Join(", ", rule.Senders));
                item.SubItems.Add(rule.Logic == MatchLogic.And ? "且(AND)" : "或(OR)");
                item.Tag = rule;
                item.ForeColor = rule.Enabled ? Color.Black : Color.Gray;
                lvRules.Items.Add(item);
            }
        }

        private async void BtnSearchEmployee_Click(object sender, EventArgs e)
        {
            string keyword = cboEmployee.Text.Trim();
            if (string.IsNullOrEmpty(keyword)) return;

            cboEmployee.Enabled = false;
            _employeeSearchResults.Clear();

            try
            {
                using (var client = new ApiClient(txtBackendUrl.Text.Trim()))
                {
                    var results = await client.SearchEmployeesAsync(keyword);
                    _employeeSearchResults = results;
                    cboEmployee.Items.Clear();
                    foreach (var emp in results)
                        cboEmployee.Items.Add($"{emp.Name}  ({emp.SAMAccountName})");
                    if (results.Count > 0)
                        cboEmployee.DroppedDown = true;
                    else
                        cboEmployee.Items.Add("（无匹配结果）");
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"搜索失败：{ex.Message}", "错误", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            finally
            {
                cboEmployee.Enabled = true;
                cboEmployee.Focus();
            }
        }

        private void CboEmpResults_SelectedIndexChanged(object sender, EventArgs e)
        {
            int idx = cboEmployee.SelectedIndex;
            if (idx < 0 || idx >= _employeeSearchResults.Count) return;
            var emp = _employeeSearchResults[idx];
            _selectedSAMAccountName = emp.SAMAccountName;
            // 回填显示名
            cboEmployee.Text = emp.Name;
        }

        private void BtnLoadProducts_Click(object sender, EventArgs e)
        {
            string current = cboProduct.SelectedItem?.ToString() ?? "";
            _ = LoadProductsAsync(current);
        }

        private async void BtnTestConnection_Click(object sender, EventArgs e)
        {
            btnTestConnection.Enabled = false;
            btnTestConnection.Text = "测试中...";
            try
            {
                using (var client = new ApiClient(txtBackendUrl.Text))
                {
                    bool ok = await client.TestConnectionAsync();
                    MessageBox.Show(ok ? "连接成功！" : "连接失败，请检查后端地址和网络。",
                        "连接测试", MessageBoxButtons.OK,
                        ok ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show($"连接异常：{ex.Message}", "连接测试", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            finally
            {
                btnTestConnection.Enabled = true;
                btnTestConnection.Text = "测试连接";
            }
        }

        private void BtnAddRule_Click(object sender, EventArgs e)
        {
            using (var form = new RuleEditForm())
            {
                if (form.ShowDialog(this) == DialogResult.OK)
                {
                    _config.Rules.Add(form.Rule);
                    RefreshRuleList();
                }
            }
        }

        private void BtnEditRule_Click(object sender, EventArgs e)
        {
            if (lvRules.SelectedItems.Count == 0)
            {
                MessageBox.Show("请先选择一条规则。", "提示", MessageBoxButtons.OK, MessageBoxIcon.Information);
                return;
            }
            var rule = (ForwardRule)lvRules.SelectedItems[0].Tag;
            using (var form = new RuleEditForm(rule))
            {
                if (form.ShowDialog(this) == DialogResult.OK)
                {
                    // rule已被原地修改
                    RefreshRuleList();
                }
            }
        }

        private void BtnDeleteRule_Click(object sender, EventArgs e)
        {
            if (lvRules.SelectedItems.Count == 0) return;
            var rule = (ForwardRule)lvRules.SelectedItems[0].Tag;
            if (MessageBox.Show($"确定删除规则 \"{rule.Name}\" 吗？", "确认删除",
                MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
            {
                _config.Rules.Remove(rule);
                RefreshRuleList();
            }
        }

        private void BtnToggleRule_Click(object sender, EventArgs e)
        {
            if (lvRules.SelectedItems.Count == 0) return;
            var rule = (ForwardRule)lvRules.SelectedItems[0].Tag;
            rule.Enabled = !rule.Enabled;
            RefreshRuleList();
        }

        private void BtnSave_Click(object sender, EventArgs e)
        {
            // 验证后端地址
            if (string.IsNullOrWhiteSpace(txtBackendUrl.Text))
            {
                MessageBox.Show("请输入后端地址。", "验证", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                tabControl.SelectedIndex = 0;
                return;
            }

            // 验证自定义JSON
            if (!string.IsNullOrWhiteSpace(txtCustomJson.Text))
            {
                try
                {
                    var serializer = new System.Web.Script.Serialization.JavaScriptSerializer();
                    serializer.Deserialize<object>(txtCustomJson.Text);
                }
                catch
                {
                    MessageBox.Show("扩展配置JSON格式不合法，请检查。", "验证", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    tabControl.SelectedIndex = 1;
                    txtCustomJson.Focus();
                    return;
                }
            }

            _config.BackendUrl = txtBackendUrl.Text.Trim();
            _config.ScanIntervalMinutes = (int)numInterval.Value;
            _config.ExtraInfo.EmployeeId = _selectedSAMAccountName;
            _config.ExtraInfo.ProductCategory = cboProduct.SelectedItem?.ToString() ?? "";
            _config.CustomJsonConfig = string.IsNullOrWhiteSpace(txtCustomJson.Text) ? "{}" : txtCustomJson.Text.Trim();

            // ScanFolders 已在 Tab 操作中实时写入 _config，无需额外赋值
            ConfigManager.Save(_config);

            MessageBox.Show("配置已保存！", "提示", MessageBoxButtons.OK, MessageBoxIcon.Information);
            this.DialogResult = DialogResult.OK;
            this.Close();
        }
    }
}
