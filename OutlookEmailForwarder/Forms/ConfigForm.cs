using System;
using System.Drawing;
using System.Windows.Forms;
using System.Collections.Generic;
using OutlookEmailForwarder.Models;
using OutlookEmailForwarder.Services;

namespace OutlookEmailForwarder.Forms
{
    public class ConfigForm : Form
    {
        private TabControl tabControl;
        // 基本设置页
        private TextBox txtBackendUrl;
        private NumericUpDown numInterval;
        private Button btnTestConnection;
        // 用户信息页
        private TextBox txtEmployeeId;
        private TextBox txtDepartment;
        private TextBox txtProductCategory;
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

        public ConfigForm()
        {
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
            var lblEmpId = new Label { Text = "工号：", Location = new Point(20, 30), AutoSize = true };
            txtEmployeeId = new TextBox { Location = new Point(120, 27), Size = new Size(200, 25) };

            var lblDept = new Label { Text = "部门：", Location = new Point(20, 70), AutoSize = true };
            txtDepartment = new TextBox { Location = new Point(120, 67), Size = new Size(200, 25) };

            var lblProduct = new Label { Text = "产品分类：", Location = new Point(20, 110), AutoSize = true };
            txtProductCategory = new TextBox { Location = new Point(120, 107), Size = new Size(200, 25) };

            var lblCustom = new Label { Text = "扩展配置(JSON)：", Location = new Point(20, 160), AutoSize = true };
            txtCustomJson = new TextBox
            {
                Location = new Point(20, 185),
                Size = new Size(540, 180),
                Multiline = true,
                ScrollBars = ScrollBars.Vertical,
                Font = new Font("Consolas", 9F)
            };
            var lblCustomTip = new Label
            {
                Text = "扩展配置用于向后端传递额外信息，无需重装插件即可调整。请输入合法的JSON格式。",
                Location = new Point(20, 370),
                Size = new Size(540, 20),
                ForeColor = Color.Gray
            };

            tabUser.Controls.AddRange(new Control[] { lblEmpId, txtEmployeeId, lblDept, txtDepartment,
                lblProduct, txtProductCategory, lblCustom, txtCustomJson, lblCustomTip });

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

            txtEmployeeId.Text = _config.ExtraInfo.EmployeeId;
            txtDepartment.Text = _config.ExtraInfo.Department;
            txtProductCategory.Text = _config.ExtraInfo.ProductCategory;
            txtCustomJson.Text = _config.CustomJsonConfig;

            RefreshRuleList();
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
            _config.ExtraInfo.EmployeeId = txtEmployeeId.Text.Trim();
            _config.ExtraInfo.Department = txtDepartment.Text.Trim();
            _config.ExtraInfo.ProductCategory = txtProductCategory.Text.Trim();
            _config.CustomJsonConfig = string.IsNullOrWhiteSpace(txtCustomJson.Text) ? "{}" : txtCustomJson.Text.Trim();

            ConfigManager.Save(_config);

            MessageBox.Show("配置已保存！", "提示", MessageBoxButtons.OK, MessageBoxIcon.Information);
            this.DialogResult = DialogResult.OK;
            this.Close();
        }
    }
}
