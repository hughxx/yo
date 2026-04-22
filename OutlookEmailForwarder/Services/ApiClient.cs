using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using OutlookEmailForwarder.Models;

namespace OutlookEmailForwarder.Services
{
    /// <summary>
    /// 后端API客户端
    /// </summary>
    public class ApiClient : IDisposable
    {
        private readonly HttpClient _http;
        private readonly JavaScriptSerializer _serializer = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        private string _baseUrl;

        public ApiClient(string baseUrl)
        {
            _baseUrl = baseUrl.TrimEnd('/');
            _http = new HttpClient
            {
                Timeout = TimeSpan.FromSeconds(30)
            };
        }

        public void UpdateBaseUrl(string baseUrl)
        {
            _baseUrl = baseUrl.TrimEnd('/');
        }

        /// <summary>
        /// 发送邮件数据到后端
        /// </summary>
        public async Task<ApiResponse> SendEmailAsync(EmailPayload payload)
        {
            try
            {
                var json = _serializer.Serialize(payload);
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                var response = await _http.PostAsync($"{_baseUrl}/api/email/receive", content);
                var body = await response.Content.ReadAsStringAsync();

                if (response.IsSuccessStatusCode)
                {
                    return _serializer.Deserialize<ApiResponse>(body) ?? new ApiResponse { Success = true };
                }

                return new ApiResponse
                {
                    Success = false,
                    Message = $"HTTP {(int)response.StatusCode}: {body}"
                };
            }
            catch (Exception ex)
            {
                return new ApiResponse
                {
                    Success = false,
                    Message = ex.Message
                };
            }
        }

        /// <summary>
        /// 上报错误信息到后端
        /// </summary>
        public async Task ReportErrorAsync(ErrorReport error)
        {
            try
            {
                var json = _serializer.Serialize(error);
                var content = new StringContent(json, Encoding.UTF8, "application/json");
                await _http.PostAsync($"{_baseUrl}/api/email/error", content);
            }
            catch
            {
                // 上报错误本身失败，静默处理
            }
        }

        /// <summary>
        /// 测试后端连通性
        /// </summary>
        public async Task<bool> TestConnectionAsync()
        {
            try
            {
                var response = await _http.GetAsync($"{_baseUrl}/api/email/ping");
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// 工号模糊查询，返回匹配的员工列表
        /// </summary>
        public async Task<List<EmployeeInfo>> SearchEmployeesAsync(string keyword)
        {
            try
            {
                var response = await _http.GetAsync($"{_baseUrl}/api/user/search?keyword={Uri.EscapeDataString(keyword)}");
                var body = await response.Content.ReadAsStringAsync();
                var result = _serializer.Deserialize<EmployeeSearchResponse>(body);
                return result?.Data ?? new List<EmployeeInfo>();
            }
            catch
            {
                return new List<EmployeeInfo>();
            }
        }

        /// <summary>
        /// 获取产品列表
        /// </summary>
        public async Task<List<string>> GetProductsAsync()
        {
            try
            {
                var response = await _http.GetAsync($"{_baseUrl}/api/products");
                var body = await response.Content.ReadAsStringAsync();
                var result = _serializer.Deserialize<ProductListResponse>(body);
                return result?.Data ?? new List<string>();
            }
            catch
            {
                return new List<string>();
            }
        }

        public void Dispose()
        {
            _http?.Dispose();
        }
    }

    public class EmployeeInfo
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public string SAMAccountName { get; set; }
    }

    public class EmployeeSearchResponse
    {
        public int Code { get; set; }
        public List<EmployeeInfo> Data { get; set; }
    }

    public class ProductListResponse
    {
        public int Code { get; set; }
        public List<string> Data { get; set; }
    }
}
