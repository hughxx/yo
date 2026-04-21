using System;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;
using OutlookEmailForwarder.Models;

namespace OutlookEmailForwarder.Forms
{
    public class RuleEditForm : Form
    {
        private TextBox txtRuleName;
        private TextBox txtKeywords;
        private TextBox txtSenders;
        private RadioButton rbAnd;
        private RadioButton rbOr;
        private Button btnOk;
        private Button btnCancel;

        public ForwardRule Rule { get; private set; }

        /// <summary>
        /// 新建规则
        /// </summary>
        public RuleEditForm() : this(null) { }

        /// <summary>
        /// 编辑已有规则
        /// </summary>
        public RuleEditForm(ForwardRule existingRule)
        {
            Rule = existingRule ?? new ForwardRule();
            InitializeComponents();
            LoadRuleToUI();
        }

        private void InitializeComponents()
        {
            this.Text = Rule.Name == "" ? "新建规则" : $"编辑规则 - {Rule.Name}";
            this.Size = new Size(480, 420);
            this.StartPosition = FormStartPosition.CenterParent;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = false;
            this.Font = new Font("Microsoft YaHei UI", 9F);

            var lblName = new Label { Text = "规则名称：", Location = new Point(20, 20), AutoSize = true };
            txtRuleName = new TextBox { Location = new Point(100, 17), Size = new Size(340, 25) };

            var lblKeywords = new Label { Text = "关键词：", Location = new Point(20, 60), AutoSize = true };
            txtKeywords = new TextBox
            {
                Location = new Point(20, 85),
                Size = new Size(420, 80),
                Multiline = true,
                ScrollBars = ScrollBars.Vertical
            };
            var lblKwTip = new Label
            {
                Text = "每行一个关键词，匹配邮件主题或正文（不区分大小写）",
                Location = new Point(20, 168),
                AutoSize = true,
                ForeColor = Color.Gray
            };

            var lblSenders = new Label { Text = "发件人：", Location = new Point(20, 195), AutoSize = true };
            txtSenders = new TextBox
            {
                Location = new Point(20, 220),
                Size = new Size(420, 80),
                Multiline = true,
                ScrollBars = ScrollBars.Vertical
            };
            var lblSenderTip = new Label
            {
                Text = "每行一个发件人地址或名称（模糊匹配，不区分大小写）",
                Location = new Point(20, 303),
                AutoSize = true,
                ForeColor = Color.Gray
            };

            var grpLogic = new GroupBox { Text = "匹配逻辑", Location = new Point(20, 325), Size = new Size(420, 45) };
            rbAnd = new RadioButton { Text = "且(AND) - 关键词和发件人同时满足", Location = new Point(10, 18), AutoSize = true };
            rbOr = new RadioButton { Text = "或(OR) - 任一条件满足即可", Location = new Point(250, 18), AutoSize = true, Checked = true };
            grpLogic.Controls.AddRange(new Control[] { rbAnd, rbOr });

            btnOk = new Button { Text = "确定", Location = new Point(270, 378), Size = new Size(80, 30) };
            btnCancel = new Button { Text = "取消", Location = new Point(360, 378), Size = new Size(80, 30) };
            btnOk.Click += BtnOk_Click;
            btnCancel.Click += (s, e) => { this.DialogResult = DialogResult.Cancel; this.Close(); };

            this.Controls.AddRange(new Control[] {
                lblName, txtRuleName,
                lblKeywords, txtKeywords, lblKwTip,
                lblSenders, txtSenders, lblSenderTip,
                grpLogic,
                btnOk, btnCancel
            });

            this.AcceptButton = btnOk;
            this.CancelButton = btnCancel;
        }

        private void LoadRuleToUI()
        {
            txtRuleName.Text = Rule.Name;
            txtKeywords.Text = string.Join(Environment.NewLine, Rule.Keywords);
            txtSenders.Text = string.Join(Environment.NewLine, Rule.Senders);
            if (Rule.Logic == MatchLogic.And)
                rbAnd.Checked = true;
            else
                rbOr.Checked = true;
        }

        private void BtnOk_Click(object sender, EventArgs e)
        {
            if (string.IsNullOrWhiteSpace(txtRuleName.Text))
            {
                MessageBox.Show("请输入规则名称。", "验证", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                txtRuleName.Focus();
                return;
            }

            var keywords = txtKeywords.Text
                .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(s => s.Trim())
                .Where(s => s.Length > 0)
                .ToList();

            var senders = txtSenders.Text
                .Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(s => s.Trim())
                .Where(s => s.Length > 0)
                .ToList();

            if (keywords.Count == 0 && senders.Count == 0)
            {
                MessageBox.Show("请至少填写一个关键词或一个发件人。", "验证", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            Rule.Name = txtRuleName.Text.Trim();
            Rule.Keywords = keywords;
            Rule.Senders = senders;
            Rule.Logic = rbAnd.Checked ? MatchLogic.And : MatchLogic.Or;

            this.DialogResult = DialogResult.OK;
            this.Close();
        }
    }
}
