using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace OutlookEmailForwarder.Services
{
    /// <summary>
    /// 已处理邮件追踪器 —— 持久化到磁盘，避免每次重复提交
    /// 真正的去重由后端完成（按 用户工号+邮件ID）
    /// 提供清空功能，用户可手动触发全量重扫
    /// </summary>
    public class ProcessedTracker
    {
        private static readonly string DataDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "OutlookEmailForwarder");
        private static readonly string TrackerPath = Path.Combine(DataDir, "processed.dat");

        private readonly HashSet<string> _processedIds = new HashSet<string>();
        private DateTime _lastProcessedTime = DateTime.MinValue;

        public ProcessedTracker()
        {
            LoadFromDisk();
        }

        public DateTime LastProcessedTime => _lastProcessedTime;
        public int Count => _processedIds.Count;

        public bool IsProcessed(string entryId)
        {
            return _processedIds.Contains(entryId);
        }

        public void MarkProcessed(string entryId, DateTime receivedTime)
        {
            _processedIds.Add(entryId);
            if (receivedTime > _lastProcessedTime)
                _lastProcessedTime = receivedTime;
        }

        /// <summary>
        /// 清空全部缓存，下次扫描会重新提交所有匹配邮件
        /// </summary>
        public void ClearAll()
        {
            _processedIds.Clear();
            _lastProcessedTime = DateTime.MinValue;
            try { File.Delete(TrackerPath); } catch { }
        }

        public void SaveToDisk()
        {
            if (!Directory.Exists(DataDir))
                Directory.CreateDirectory(DataDir);

            var lines = new List<string> { _lastProcessedTime.ToString("o") };
            lines.AddRange(_processedIds);
            File.WriteAllLines(TrackerPath, lines);
        }

        private void LoadFromDisk()
        {
            if (!File.Exists(TrackerPath)) return;
            try
            {
                var lines = File.ReadAllLines(TrackerPath);
                if (lines.Length == 0) return;
                if (DateTime.TryParse(lines[0], out var t))
                    _lastProcessedTime = t;
                for (int i = 1; i < lines.Length; i++)
                    if (!string.IsNullOrWhiteSpace(lines[i]))
                        _processedIds.Add(lines[i].Trim());
            }
            catch
            {
                _processedIds.Clear();
                _lastProcessedTime = DateTime.MinValue;
            }
        }

        public void Cleanup(int maxCount = 10000)
        {
            if (_processedIds.Count > maxCount)
            {
                var keep = _processedIds.Skip(_processedIds.Count - maxCount).ToList();
                _processedIds.Clear();
                foreach (var id in keep) _processedIds.Add(id);
            }
        }
    }
}
