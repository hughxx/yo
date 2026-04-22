using System;
using System.Collections.Generic;

namespace OutlookEmailForwarder.Models
{
    /// <summary>
    /// 插件完整配置
    /// </summary>
    [Serializable]
    public class AppConfig
    {
        /// <summary>
        /// 后端API地址，用户可配置（如 http://192.168.1.100:5000）
        /// </summary>
        public string BackendUrl { get; set; } = "http://localhost:5000";

        /// <summary>
        /// 定时扫描间隔（分钟）
        /// </summary>
        public int ScanIntervalMinutes { get; set; } = 5;

        /// <summary>
        /// 转发规则列表
        /// </summary>
        public List<ForwardRule> Rules { get; set; } = new List<ForwardRule>();

        /// <summary>
        /// 扫描文件夹列表。空列表时退回扫所有账户的默认收件箱。
        /// </summary>
        public List<ScanFolderConfig> ScanFolders { get; set; } = new List<ScanFolderConfig>();

        /// <summary>
        /// 用户扩展信息（工号、部门、产品分类等）
        /// </summary>
        public UserExtraInfo ExtraInfo { get; set; } = new UserExtraInfo();

        /// <summary>
        /// 用户自定义扩展JSON（未来扩展用，不用重装插件）
        /// </summary>
        public string CustomJsonConfig { get; set; } = "{}";
    }

    [Serializable]
    public class ScanFolderConfig
    {
        /// <summary>Outlook 完整路径，如 \\账户名\收件箱</summary>
        public string Path { get; set; } = "";

        /// <summary>界面显示名称</summary>
        public string DisplayName { get; set; } = "";

        /// <summary>是否启用（勾选）</summary>
        public bool Enabled { get; set; } = false;

        /// <summary>true = 定时反复扫描；false = 扫一次后自动禁用</summary>
        public bool Recurring { get; set; } = false;

        /// <summary>邮件数量，仅用于界面显示，-1 表示未知</summary>
        public int ItemCount { get; set; } = -1;
    }

    /// <summary>
    /// 用户身份/业务扩展信息
    /// </summary>
    [Serializable]
    public class UserExtraInfo
    {
        /// <summary>
        /// 工号（sAMAccountName）
        /// </summary>
        public string EmployeeId { get; set; } = "";

        /// <summary>
        /// 负责的产品分类
        /// </summary>
        public string ProductCategory { get; set; } = "";
    }
}
