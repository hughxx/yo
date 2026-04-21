using System;
using System.IO;
using System.Web.Script.Serialization;
using OutlookEmailForwarder.Models;

namespace OutlookEmailForwarder.Services
{
    /// <summary>
    /// 配置管理器：读写JSON配置文件
    /// </summary>
    public class ConfigManager
    {
        private static readonly JavaScriptSerializer Serializer = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        private static readonly string ConfigDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "OutlookEmailForwarder");
        private static readonly string ConfigPath = Path.Combine(ConfigDir, "config.json");

        private static AppConfig _cache;

        public static AppConfig Load()
        {
            if (_cache != null) return _cache;

            if (!File.Exists(ConfigPath))
            {
                _cache = new AppConfig();
                Save(_cache);
                return _cache;
            }

            try
            {
                var json = File.ReadAllText(ConfigPath);
                _cache = Serializer.Deserialize<AppConfig>(json) ?? new AppConfig();
            }
            catch
            {
                _cache = new AppConfig();
            }
            return _cache;
        }

        public static void Save(AppConfig config)
        {
            _cache = config;
            if (!Directory.Exists(ConfigDir))
                Directory.CreateDirectory(ConfigDir);

            var json = Serializer.Serialize(config);
            // 简单格式化
            json = FormatJson(json);
            File.WriteAllText(ConfigPath, json);
        }

        public static void Reload()
        {
            _cache = null;
            Load();
        }

        /// <summary>
        /// 简单的JSON格式化（缩进），不依赖第三方库
        /// </summary>
        private static string FormatJson(string json)
        {
            int indent = 0;
            bool inString = false;
            var sb = new System.Text.StringBuilder();

            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];

                if (c == '"' && (i == 0 || json[i - 1] != '\\'))
                {
                    inString = !inString;
                    sb.Append(c);
                    continue;
                }

                if (inString)
                {
                    sb.Append(c);
                    continue;
                }

                switch (c)
                {
                    case '{':
                    case '[':
                        sb.Append(c);
                        sb.AppendLine();
                        indent++;
                        sb.Append(new string(' ', indent * 2));
                        break;
                    case '}':
                    case ']':
                        sb.AppendLine();
                        indent--;
                        sb.Append(new string(' ', indent * 2));
                        sb.Append(c);
                        break;
                    case ',':
                        sb.Append(c);
                        sb.AppendLine();
                        sb.Append(new string(' ', indent * 2));
                        break;
                    case ':':
                        sb.Append(c);
                        sb.Append(' ');
                        break;
                    default:
                        sb.Append(c);
                        break;
                }
            }
            return sb.ToString();
        }
    }
}
