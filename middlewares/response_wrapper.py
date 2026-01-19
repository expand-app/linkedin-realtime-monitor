import json
from django.utils.deprecation import MiddlewareMixin


class CampaignManagerResponseWrapperMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        # 只处理 campaign-manager 应用的 API 接口
        if request.path.startswith("/campaign-manager/"):

            # 文件下载接口通常会包含该响应头
            if response.has_header("Content-Disposition"):
                return response

            # 只处理 JSON 响应
            content_type = response.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    # 解码原始数据
                    data = json.loads(response.content)

                    # 包装成 {"data": original_data}
                    wrapped_data = {"data": data}
                    response.content = json.dumps(wrapped_data)
                    response["Content-Length"] = str(len(response.content))

                except Exception as e:
                    # 避免包装失败导致请求异常
                    pass

        return response
