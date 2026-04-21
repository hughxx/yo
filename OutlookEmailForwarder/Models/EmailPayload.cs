using System;
using System.Collections.Generic;

namespace OutlookEmailForwarder.Models
{
    /// <summary>
    /// 发送到后端的邮件数据
    /// </summary>
    [Serializable]
    public class EmailPayload
    {
        /// <summary>
        /// 邮件唯一标识（Outlook EntryID）
        /// </summary>
        public string EmailId { get; set; }

        /// <summary>
        /// 邮件主题
        /// </summary>
        public string Subject { get; set; }

        /// <summary>
        /// 发件人地址
        /// </summary>
        public string SenderEmail { get; set; }

        /// <summary>
        /// 发件人显示名称
        /// </summary>
        public string SenderName { get; set; }

        /// <summary>
        /// 收件时间
        /// </summary>
        public DateTime ReceivedTime { get; set; }

        /// <summary>
        /// HTML正文（内嵌图片已转为base64 data URI）
        /// </summary>
        public string HtmlBody { get; set; }

        /// <summary>
        /// 纯文本正文（备用）
        /// </summary>
        public string TextBody { get; set; }

        /// <summary>
        /// 内嵌图片列表（CID -> base64）
        /// </summary>
        public List<EmbeddedImage> EmbeddedImages { get; set; } = new List<EmbeddedImage>();

        /// <summary>
        /// 匹配的规则名称
        /// </summary>
        public string MatchedRuleName { get; set; }

        /// <summary>
        /// 用户扩展信息
        /// </summary>
        public UserExtraInfo ExtraInfo { get; set; }

        /// <summary>
        /// 用户自定义扩展JSON
        /// </summary>
        public string CustomJsonConfig { get; set; }
    }

    [Serializable]
    public class EmbeddedImage
    {
        public string ContentId { get; set; }
        public string FileName { get; set; }
        public string Base64Data { get; set; }
        public string ContentType { get; set; }
    }

    /// <summary>
    /// 后端API统一响应
    /// </summary>
    [Serializable]
    public class ApiResponse
    {
        public bool Success { get; set; }
        public string Message { get; set; }
    }

    /// <summary>
    /// 错误上报数据
    /// </summary>
    [Serializable]
    public class ErrorReport
    {
        public string ErrorMessage { get; set; }
        public string StackTrace { get; set; }
        public DateTime OccurredAt { get; set; }
        public string EmailId { get; set; }
        public UserExtraInfo ExtraInfo { get; set; }
    }
}
