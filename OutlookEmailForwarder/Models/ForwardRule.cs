using System;
using System.Collections.Generic;

namespace OutlookEmailForwarder.Models
{
    /// <summary>
    /// 单条转发规则
    /// </summary>
    [Serializable]
    public class ForwardRule
    {
        public string Id { get; set; } = Guid.NewGuid().ToString("N");
        public string Name { get; set; } = "";
        public bool Enabled { get; set; } = true;

        /// <summary>
        /// 关键词列表（匹配邮件主题或正文）
        /// </summary>
        public List<string> Keywords { get; set; } = new List<string>();

        /// <summary>
        /// 发件人列表（匹配发件人地址）
        /// </summary>
        public List<string> Senders { get; set; } = new List<string>();

        /// <summary>
        /// 匹配逻辑：And = 关键词和发件人同时满足，Or = 任一满足
        /// </summary>
        public MatchLogic Logic { get; set; } = MatchLogic.Or;
    }

    public enum MatchLogic
    {
        And,
        Or
    }
}
