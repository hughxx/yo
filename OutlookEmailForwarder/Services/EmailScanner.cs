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
        /// 扫描所有账户的收件箱
        /// </summary>
        public List<MatchedEmail> ScanInbox(Outlook.Application app, List<ForwardRule> rules,
            ProcessedTracker tracker, Action<string> log = null)
        {
            var results = new List<MatchedEmail>();
            if (rules == null || rules.Count == 0) return results;

            var enabledRules = rules.Where(r => r.Enabled).ToList();
            if (enabledRules.Count == 0) return results;

            var ns = app.GetNamespace("MAPI");
            Outlook.Stores stores = null;

            try
            {
                stores = ns.Stores;
                int storeCount = stores.Count;
                log?.Invoke($"发现 {storeCount} 个邮件账户/存储");

                for (int s = 1; s <= storeCount; s++)
                {
                    Outlook.Store store = null;
                    Outlook.MAPIFolder inbox = null;
                    Outlook.Items items = null;

                    try
                    {
                        store = stores[s];
                        string storeName = store.DisplayName ?? $"Store#{s}";

                        try
                        {
                            inbox = store.GetDefaultFolder(Outlook.OlDefaultFolders.olFolderInbox);
                        }
                        catch
                        {
                            log?.Invoke($"[{storeName}] 跳过（无收件箱）");
                            continue;
                        }

                        items = inbox.Items;
                        items.Sort("[ReceivedTime]", true);

                        int totalCount = items.Count;
                        log?.Invoke($"[{storeName}] 收件箱共 {totalCount} 封邮件，开始遍历...");

                        int scanned = 0;
                        int skippedProcessed = 0;
                        int skippedNotMail = 0;
                        int skippedError = 0;
                        int matched = 0;
                        int maxScan = 2000;

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

                                // 插件端只做轻量标记避免同一次运行期间重复扫描
                                // 真正的去重交给后端（按 用户工号+邮件ID）
                                if (tracker.IsProcessed(mail.EntryID))
                                {
                                    skippedProcessed++;
                                    curItem = items.GetNext();
                                    continue;
                                }

                                // 时间截断优化（非首次扫描时）
                                if (tracker.LastProcessedTime > DateTime.MinValue &&
                                    mail.ReceivedTime < tracker.LastProcessedTime.AddDays(-1))
                                {
                                    log?.Invoke($"[{storeName}] 到达历史边界，停止（{mail.ReceivedTime:g}）");
                                    break;
                                }

                                foreach (var rule in enabledRules)
                                {
                                    if (MatchesRule(mail, rule))
                                    {
                                        matched++;
                                        log?.Invoke($"  命中[{rule.Name}]：{mail.Subject}");
                                        results.Add(new MatchedEmail
                                        {
                                            Mail = mail,
                                            RuleName = rule.Name
                                        });
                                        break;
                                    }
                                }
                            }
                            catch (Exception ex)
                            {
                                skippedError++;
                                log?.Invoke($"  第{scanned}封处理异常：{ex.Message}");
                            }

                            // GetNext 放在最外层，确保任何情况都往前走
                            try
                            {
                                curItem = items.GetNext();
                            }
                            catch
                            {
                                // GetNext 失败则终止本 store 的遍历
                                log?.Invoke($"[{storeName}] 遍历中断（GetNext异常）");
                                break;
                            }
                        }

                        log?.Invoke($"[{storeName}] 完成：遍历 {scanned}/{totalCount} 封，" +
                                    $"已处理 {skippedProcessed}，非邮件 {skippedNotMail}，" +
                                    $"异常 {skippedError}，命中 {matched} 封");
                    }
                    finally
                    {
                        if (items != null) try { Marshal.ReleaseComObject(items); } catch { }
                        if (inbox != null) try { Marshal.ReleaseComObject(inbox); } catch { }
                        if (store != null) try { Marshal.ReleaseComObject(store); } catch { }
                    }
                }
            }
            finally
            {
                if (stores != null) try { Marshal.ReleaseComObject(stores); } catch { }
            }

            return results;
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
                Subject = mail.Subject ?? "",
                SenderEmail = mail.SenderEmailAddress ?? "",
                SenderName = mail.SenderName ?? "",
                ReceivedTime = mail.ReceivedTime,
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
