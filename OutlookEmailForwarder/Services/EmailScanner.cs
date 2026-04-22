using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using OutlookEmailForwarder.Models;
using Outlook = Microsoft.Office.Interop.Outlook;

namespace OutlookEmailForwarder.Services
{
    public class EmailScanner
    {
        /// <summary>
        /// 扫描文件夹。
        /// scanFolders 为空时退回扫所有账户的默认收件箱（兼容未配置状态）。
        /// 扫完后，非 Recurring 的文件夹会被自动置为 Enabled=false（调用方负责保存配置）。
        /// </summary>
        public List<MatchedEmail> ScanInbox(Outlook.Application app, List<ForwardRule> rules,
            ProcessedTracker tracker, Action<string> log = null,
            List<ScanFolderConfig> scanFolders = null)
        {
            var results = new List<MatchedEmail>();
            if (rules == null || rules.Count == 0) return results;

            var enabledRules = rules.Where(r => r.Enabled).ToList();
            if (enabledRules.Count == 0) return results;

            var ns = app.GetNamespace("MAPI");
            Outlook.Stores stores = null;

            // (folder对象, 显示标签, 对应配置项 or null)
            var foldersToScan = new List<(Outlook.MAPIFolder Folder, string Label, ScanFolderConfig Config)>();

            try
            {
                stores = ns.Stores;

                var configured = scanFolders?.Where(f => f.Enabled).ToList();

                if (configured == null || configured.Count == 0)
                {
                    // 未配置 → 扫所有账户默认收件箱
                    log?.Invoke($"发现 {stores.Count} 个邮件账户/存储");
                    for (int s = 1; s <= stores.Count; s++)
                    {
                        Outlook.Store store = null;
                        try
                        {
                            store = stores[s];
                            string storeName = store.DisplayName ?? $"Store#{s}";
                            try
                            {
                                var inbox = store.GetDefaultFolder(Outlook.OlDefaultFolders.olFolderInbox);
                                foldersToScan.Add((inbox, $"{storeName} · 收件箱", null));
                            }
                            catch { log?.Invoke($"[{storeName}] 无默认收件箱，跳过"); }
                        }
                        finally { if (store != null) try { Marshal.ReleaseComObject(store); } catch { } }
                    }
                }
                else
                {
                    // 按配置扫描
                    foreach (var cfg in configured)
                    {
                        var folder = TryGetFolderByPath(ns, cfg.Path);
                        if (folder != null)
                            foldersToScan.Add((folder, cfg.DisplayName, cfg));
                        else
                            log?.Invoke($"[配置文件夹] 找不到路径：{cfg.Path}，跳过");
                    }
                }

                foreach (var (folder, label, cfg) in foldersToScan)
                {
                    if (folder == null) continue;
                    Outlook.Items items = null;
                    try
                    {
                        items = folder.Items;
                        items.Sort("[ReceivedTime]", true);

                        int totalCount = items.Count;
                        bool recurring = cfg?.Recurring ?? true;
                        log?.Invoke($"[{label}] 共 {totalCount} 封，{(recurring ? "定时扫描" : "单次扫描")}");

                        int scanned = 0, skippedProcessed = 0, skippedNotMail = 0,
                            skippedError = 0, matched = 0;
                        const int maxScan = 2000;

                        object curItem = items.GetFirst();
                        while (curItem != null && scanned + skippedNotMail + skippedError < maxScan)
                        {
                            var mail = curItem as Outlook.MailItem;
                            if (mail == null)
                            {
                                skippedNotMail++;
                                try { Marshal.ReleaseComObject(curItem); } catch { }
                                curItem = items.GetNext();
                                continue;
                            }

                            try
                            {
                                scanned++;

                                if (tracker.IsProcessed(mail.EntryID))
                                {
                                    skippedProcessed++;
                                    curItem = items.GetNext();
                                    continue;
                                }

                                // 定时收件箱才做时间截断；单次文件夹全量扫
                                if (recurring &&
                                    tracker.LastProcessedTime > DateTime.MinValue &&
                                    mail.ReceivedTime < tracker.LastProcessedTime.AddDays(-1))
                                {
                                    log?.Invoke($"[{label}] 到达历史边界，停止（{mail.ReceivedTime:g}）");
                                    break;
                                }

                                foreach (var rule in enabledRules)
                                {
                                    if (MatchesRule(mail, rule))
                                    {
                                        matched++;
                                        log?.Invoke($"  命中[{rule.Name}]：{mail.Subject}");
                                        results.Add(new MatchedEmail { Mail = mail, RuleName = rule.Name });
                                        break;
                                    }
                                }
                            }
                            catch (Exception ex)
                            {
                                skippedError++;
                                log?.Invoke($"  第{scanned}封处理异常：{ex.Message}");
                            }

                            try { curItem = items.GetNext(); }
                            catch { log?.Invoke($"[{label}] 遍历中断"); break; }
                        }

                        log?.Invoke($"[{label}] 完成：遍历 {scanned}/{totalCount}，命中 {matched}");

                        // 单次文件夹扫完后自动禁用
                        if (cfg != null && !cfg.Recurring)
                            cfg.Enabled = false;
                    }
                    finally
                    {
                        if (items != null) try { Marshal.ReleaseComObject(items); } catch { }
                        try { Marshal.ReleaseComObject(folder); } catch { }
                    }
                }
            }
            finally
            {
                if (stores != null) try { Marshal.ReleaseComObject(stores); } catch { }
            }

            return results;
        }

        /// <summary>
        /// 按 Outlook 完整路径（如 \\账户名\收件箱\归档）定位文件夹，找不到返回 null
        /// </summary>
        private Outlook.MAPIFolder TryGetFolderByPath(Outlook.NameSpace ns, string fullPath)
        {
            // 路径格式：\\StoreName\Folder\SubFolder（或 /StoreName/Folder/SubFolder）
            string normalized = fullPath.Replace('/', '\\').TrimStart('\\');
            string[] parts = normalized.Split(new[] { '\\' }, StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 1) return null;

            string storeName = parts[0];
            Outlook.Stores stores = null;
            Outlook.Store targetStore = null;
            try
            {
                stores = ns.Stores;
                for (int i = 1; i <= stores.Count; i++)
                {
                    var s = stores[i];
                    if (string.Equals(s.DisplayName, storeName, StringComparison.OrdinalIgnoreCase))
                    {
                        targetStore = s;
                        break;
                    }
                    Marshal.ReleaseComObject(s);
                }
            }
            finally
            {
                if (stores != null) Marshal.ReleaseComObject(stores);
            }

            if (targetStore == null) return null;

            Outlook.MAPIFolder current = null;
            try
            {
                current = targetStore.GetRootFolder();
                for (int i = 1; i < parts.Length; i++)
                {
                    Outlook.Folders subFolders = null;
                    Outlook.MAPIFolder next = null;
                    try
                    {
                        subFolders = current.Folders;
                        try { next = subFolders[parts[i]]; } catch { }
                    }
                    finally
                    {
                        if (subFolders != null) Marshal.ReleaseComObject(subFolders);
                    }
                    Marshal.ReleaseComObject(current);
                    current = next;
                    if (current == null) return null;
                }
                return current;
            }
            catch
            {
                if (current != null) try { Marshal.ReleaseComObject(current); } catch { }
                return null;
            }
            finally
            {
                Marshal.ReleaseComObject(targetStore);
            }
        }

        private bool MatchesRule(Outlook.MailItem mail, ForwardRule rule)
        {
            bool keywordMatch = false;
            bool senderMatch = false;

            if (rule.Keywords != null && rule.Keywords.Count > 0)
            {
                string subject = (mail.Subject ?? "").ToLowerInvariant();
                string body = (mail.Body ?? "").ToLowerInvariant();
                keywordMatch = rule.Keywords.Any(kw =>
                {
                    string kwLower = kw.ToLowerInvariant().Trim();
                    if (kwLower.Length == 0) return false;
                    return subject.Contains(kwLower) || body.Contains(kwLower);
                });
            }
            else
            {
                keywordMatch = true;
            }

            if (rule.Senders != null && rule.Senders.Count > 0)
            {
                string senderAddr = (mail.SenderEmailAddress ?? "").ToLowerInvariant();
                string senderName = (mail.SenderName ?? "").ToLowerInvariant();
                senderMatch = rule.Senders.Any(s =>
                {
                    string sLower = s.ToLowerInvariant().Trim();
                    if (sLower.Length == 0) return false;
                    return senderAddr.Contains(sLower) || senderName.Contains(sLower);
                });
            }
            else
            {
                senderMatch = true;
            }

            bool hasKeywords = rule.Keywords != null && rule.Keywords.Count > 0;
            bool hasSenders = rule.Senders != null && rule.Senders.Count > 0;
            if (!hasKeywords && !hasSenders)
                return false;

            switch (rule.Logic)
            {
                case MatchLogic.And:
                    return keywordMatch && senderMatch;
                case MatchLogic.Or:
                    if (hasKeywords && hasSenders)
                        return keywordMatch || senderMatch;
                    if (hasKeywords) return keywordMatch;
                    if (hasSenders) return senderMatch;
                    return false;
                default:
                    return false;
            }
        }

        public EmailPayload ConvertToPayload(Outlook.MailItem mail, string ruleName, AppConfig config)
        {
            var payload = new EmailPayload
            {
                EmailId = mail.EntryID,
                ConversationTopic = mail.ConversationTopic ?? "",
                Subject = mail.Subject ?? "",
                SenderEmail = mail.SenderEmailAddress ?? "",
                SenderName = mail.SenderName ?? "",
                ReceivedTime = mail.ReceivedTime.ToString("o"),  // ISO 8601，避免 /Date(xxx)/ 序列化问题
                TextBody = mail.Body ?? "",
                MatchedRuleName = ruleName,
                ExtraInfo = config.ExtraInfo,
                CustomJsonConfig = config.CustomJsonConfig
            };

            string htmlBody = mail.HTMLBody ?? "";
            var embeddedImages = new List<EmbeddedImage>();

            if (mail.Attachments != null)
            {
                for (int i = 1; i <= mail.Attachments.Count; i++)
                {
                    Outlook.Attachment att = null;
                    try
                    {
                        att = mail.Attachments[i];
                        string contentId = null;
                        try
                        {
                            contentId = att.PropertyAccessor.GetProperty(
                                "http://schemas.microsoft.com/mapi/proptag/0x3712001F") as string;
                        }
                        catch { }

                        if (!string.IsNullOrEmpty(contentId) && IsImageFile(att.FileName))
                        {
                            string tempFile = System.IO.Path.Combine(
                                System.IO.Path.GetTempPath(),
                                Guid.NewGuid().ToString("N") + "_" + att.FileName);
                            try
                            {
                                att.SaveAsFile(tempFile);
                                byte[] fileBytes = System.IO.File.ReadAllBytes(tempFile);
                                string base64 = Convert.ToBase64String(fileBytes);
                                string contentType = GetContentType(att.FileName);

                                embeddedImages.Add(new EmbeddedImage
                                {
                                    ContentId = contentId,
                                    FileName = att.FileName,
                                    Base64Data = base64,
                                    ContentType = contentType
                                });

                                htmlBody = htmlBody.Replace(
                                    $"cid:{contentId}",
                                    $"data:{contentType};base64,{base64}");
                            }
                            finally
                            {
                                try { System.IO.File.Delete(tempFile); } catch { }
                            }
                        }
                    }
                    finally
                    {
                        if (att != null) try { Marshal.ReleaseComObject(att); } catch { }
                    }
                }
            }

            payload.HtmlBody = htmlBody;
            payload.EmbeddedImages = embeddedImages;

            return payload;
        }

        private bool IsImageFile(string fileName)
        {
            if (string.IsNullOrEmpty(fileName)) return false;
            string ext = System.IO.Path.GetExtension(fileName).ToLowerInvariant();
            return ext == ".png" || ext == ".jpg" || ext == ".jpeg" ||
                   ext == ".gif" || ext == ".bmp" || ext == ".webp";
        }

        private string GetContentType(string fileName)
        {
            string ext = System.IO.Path.GetExtension(fileName).ToLowerInvariant();
            switch (ext)
            {
                case ".png": return "image/png";
                case ".jpg":
                case ".jpeg": return "image/jpeg";
                case ".gif": return "image/gif";
                case ".bmp": return "image/bmp";
                case ".webp": return "image/webp";
                default: return "application/octet-stream";
            }
        }
    }

    public class MatchedEmail
    {
        public Outlook.MailItem Mail { get; set; }
        public string RuleName { get; set; }
    }
}
