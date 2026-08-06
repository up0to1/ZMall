

> ## Documentation Index
> Fetch the complete documentation index at: https://platform.qianwenai.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# 图像编辑 - 万相2.7/2.6/2.5

> 万相图像编辑模型系列支持多图输入与多图输出，通过文本指令实现图像编辑、多图融合、主体特征保持、目标检测与分割等能力。

## 快速开始

本示例将演示如何使用`wan2.7-image-pro`模型，基于2张输入图片和提示词生成编辑后的图像。

提示词：把图2的涂鸦喷绘在图1的汽车上

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "19%", paddingBottom: "8px"}}>**输入图像1**</th>
      <th style={{textAlign: "left", width: "41%", paddingBottom: "8px"}}>**输入图像2**</th>
      <th style={{textAlign: "left", width: "40%", paddingBottom: "8px"}}>**输出图像（wan2.7-image-pro）**</th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="car" src="https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top"}}>
        <img alt="paint" src="https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>
    
      <td style={{verticalAlign: "top"}}>
        <img alt="output" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1063463.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>
    </tr>
  </tbody>
</table>

<Tabs>
  <Tab title="同步调用">
    <Note>请确保 DashScope Python SDK 版本不低于 `1.25.15`，DashScope Java SDK 版本不低于 `2.22.13`。</Note>

    <CodeGroup>
      ```python
      import os
      import dashscope
      from dashscope.aigc.image_generation import ImageGeneration
      from dashscope.api_entities.dashscope_response import Message
    
      dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
    
      # 如果未设置环境变量，请将下行替换为：api_key="sk-xxx"
      api_key = os.getenv("DASHSCOPE_API_KEY")
    
      message = Message(
        role="user",
        # 支持本地文件，如 "image": "file://car.png"
        content=[
          {
            "text": "把图2的涂鸦喷绘在图1的汽车上"
          },
          {
            "image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp"
          },
          {
            "image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp"
          }
        ]
      )
      print("----同步调用，请稍候----")
      rsp = ImageGeneration.call(
          model='wan2.7-image-pro',
          api_key=api_key,
          messages=[message],
          watermark=False,
          n=1,
          size="2K"
        )
    
      print(rsp)
      ```
    
      ```json
      {
          "status_code": 200,
          "request_id": "81d868c6-6ce1-92d8-a90d-d2ee71xxxxxx",
          "code": "",
          "message": "",
          "output": {
              "text": null,
              "finish_reason": null,
              "choices": [
                  {
                      "finish_reason": "stop",
                      "message": {
                          "role": "assistant",
                          "content": [
                              {
                                  "image": "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/xxxxxx.png?Expires=xxxxxx",
                                  "type": "image"
                              }
                          ]
                      }
                  }
              ],
              "audio": null,
              "finished": true
          },
          "usage": {
              "input_tokens": 18790,
              "output_tokens": 2,
              "characters": 0,
              "image_count": 1,
              "size": "2985*1405",
              "total_tokens": 18792
          }
      }
      ```
    
      ```java
      import com.alibaba.dashscope.aigc.imagegeneration.*;
      import com.alibaba.dashscope.exception.ApiException;
      import com.alibaba.dashscope.exception.NoApiKeyException;
      import com.alibaba.dashscope.exception.UploadFileException;
      import com.alibaba.dashscope.utils.Constants;
      import com.alibaba.dashscope.utils.JsonUtils;
    
      import java.util.Arrays;
      import java.util.Collections;
    
      /**
       * wan2.7-image-pro 图像编辑 - 同步调用示例
       */
      public class Main {
    
        static {
          Constants.baseHttpApiUrl = "https://dashscope.aliyuncs.com/api/v1";
        }
    
        // 如果未配置环境变量，请将下行替换为：apiKey="sk-xxx"
        static String apiKey = System.getenv("DASHSCOPE_API_KEY");
    
        public static void basicCall() throws ApiException, NoApiKeyException, UploadFileException {
          // 构建多图输入消息
          ImageGenerationMessage message = ImageGenerationMessage.builder()
            .role("user")
            .content(Arrays.asList(
              // 支持多图输入，提供多张参考图
              Collections.singletonMap("text", "把图2的涂鸦喷绘在图1的汽车上"),
              Collections.singletonMap("image", "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp"),
              Collections.singletonMap("image", "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp")
            )).build();
    
          // 图像编辑使用普通同步调用，无需设置 stream 和 enable_interleave
          ImageGenerationParam param = ImageGenerationParam.builder()
            .apiKey(apiKey)
            .model("wan2.7-image-pro")
            .messages(Collections.singletonList(message))
            .n(1)
            .size("2K")
            .build();
    
          ImageGeneration imageGeneration = new ImageGeneration();
          ImageGenerationResult result = null;
          try {
            System.out.println("---同步调用图像编辑，请稍候----");
            result = imageGeneration.call(param);
          } catch (ApiException | NoApiKeyException | UploadFileException e) {
            throw new RuntimeException(e.getMessage());
          }
          System.out.println(JsonUtils.toJson(result));
        }
    
        public static void main(String[] args) {
          try {
            basicCall();
          } catch (ApiException | NoApiKeyException | UploadFileException e) {
            System.out.println(e.getMessage());
          }
        }
      }
      ```
    
      ```json
      {
          "requestId": "1bf6173a-e8de-9f75-94d3-5e618f875xxx",
          "usage": {
              "input_tokens": 18790,
              "output_tokens": 2,
              "total_tokens": 18792,
              "image_count": 1,
              "size": "2985*1405"
          },
          "output": {
              "choices": [
                  {
                      "finish_reason": "stop",
                      "message": {
                          "role": "assistant",
                          "content": [
                              {
                                  "image": "https://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/xxxxxx.png?Expires=xxxxxx",
                                  "type": "image"
                              }
                          ]
                      }
                  }
              ],
              "finished": true
          },
          "status_code": 200,
          "code": "",
          "message": ""
      }
      ```
    
      ```bash
      curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation' \
      --header 'Content-Type: application/json' \
      --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
      --data '{
          "model": "wan2.7-image-pro",
          "input": {
              "messages": [
                  {
                      "role": "user",
                      "content": [
                          {"image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp"},
                          {"image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp"},
                          {"text": "把图2的涂鸦喷绘在图1的汽车上"}
                      ]
                  }
              ]
          },
          "parameters": {
              "size": "2K",
              "n": 1,
              "watermark": false
          }
      }'
      ```
    
      ```json
      {
          "output": {
              "choices": [
                  {
                      "finish_reason": "stop",
                      "message": {
                          "content": [
                              {
                                  "image": "https://dashscope-xxx.oss-xxx.aliyuncs.com/xxx.png?Expires=xxx",
                                  "type": "image"
                              }
                          ],
                          "role": "assistant"
                      }
                  }
              ],
              "finished": true
          },
          "usage": {
              "image_count": 1,
              "input_tokens": 10867,
              "output_tokens": 2,
              "size": "1488*704",
              "total_tokens": 10869
          },
          "request_id": "71dfc3c6-f796-9972-97e4-bc4efc4faxxx"
      }
      ```
    </CodeGroup>
  </Tab>

  <Tab title="异步调用">
    <Note>请确保 DashScope Python SDK 版本不低于 `1.25.15`，DashScope Java SDK 版本不低于 `2.22.13`。</Note>

    <CodeGroup>
      ```python
      import os
      import dashscope
      from dashscope.aigc.image_generation import ImageGeneration
      from dashscope.api_entities.dashscope_response import Message
      from http import HTTPStatus
    
      dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
    
      # 如果未设置环境变量，请将下行替换为：api_key="sk-xxx"
      api_key = os.getenv("DASHSCOPE_API_KEY")
    
      # 创建异步任务
      def create_async_task():
        print("正在创建异步任务...")
        message = Message(
          role="user",
          content=[
            {'text': '把图2的涂鸦喷绘在图1的汽车上'},
            {'image': 'https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp'},
            {'image': 'https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp'}
          ]
        )
        response = ImageGeneration.async_call(
          model="wan2.7-image-pro",
          api_key=api_key,
          messages=[message],
          watermark=False,
          n=1,
          size="2K"
        )
    
        if response.status_code == 200:
          print("任务创建成功:", response)
          return response
        else:
          raise Exception(f"任务创建失败: {response.code} - {response.message}")
    
      # 等待任务完成
      def wait_for_completion(task_response):
        print("等待任务完成...")
        status = ImageGeneration.wait(task=task_response, api_key=api_key)
    
        if status.output.task_status == "SUCCEEDED":
          print("任务成功!")
          print("响应:", status)
        else:
          raise Exception(f"任务失败，状态: {status.output.task_status}")
    
      # 查询异步任务状态
      def fetch_task_status(task):
        print("查询任务状态...")
        status = ImageGeneration.fetch(task=task, api_key=api_key)
    
        if status.status_code == HTTPStatus.OK:
          print("任务状态:", status.output.task_status)
          print("响应详情:", status)
        else:
          print(f"查询失败: {status.code} - {status.message}")
    
      # 取消异步任务
      def cancel_task(task):
        print("取消任务...")
        response = ImageGeneration.cancel(task=task, api_key=api_key)
    
        if response.status_code == HTTPStatus.OK:
          print("任务已取消:", response.output.task_status)
        else:
          print(f"取消失败: {response.code} - {response.message}")
    
      # 主流程
      if __name__ == "__main__":
        task = create_async_task()
        wait_for_completion(task)
      ```
    
      ```json
      {
        "status_code": 200,
        "request_id": "4fb3050f-de57-4a24-84ff-e37ee5xxxxxx",
        "code": "",
        "message": "",
        "output": {
          "text": null,
          "finish_reason": null,
          "choices": null,
          "audio": null,
          "task_id": "127ec645-118f-4884-955d-0eba8dxxxxxx",
          "task_status": "PENDING"
        },
        "usage": {
          "input_tokens": 0,
          "output_tokens": 0,
          "characters": 0
        }
      }
      ```
    
      ```java
      import com.alibaba.dashscope.aigc.imagegeneration.*;
      import com.alibaba.dashscope.exception.ApiException;
      import com.alibaba.dashscope.exception.NoApiKeyException;
      import com.alibaba.dashscope.exception.UploadFileException;
      import com.alibaba.dashscope.utils.Constants;
      import com.alibaba.dashscope.utils.JsonUtils;
    
      import java.util.Arrays;
      import java.util.Collections;
    
      /**
       * wan2.7-image-pro 图像编辑 - 异步调用示例
       */
      public class Main {
    
        static {
          Constants.baseHttpApiUrl = "https://dashscope.aliyuncs.com/api/v1";
        }
    
        // 如果未配置环境变量，请将下行替换为：apiKey="sk-xxx"
        static String apiKey = System.getenv("DASHSCOPE_API_KEY");
    
        public static void asyncCall() throws ApiException, NoApiKeyException, UploadFileException {
          // 构建多图输入消息
          ImageGenerationMessage message = ImageGenerationMessage.builder()
            .role("user")
            .content(Arrays.asList(
              // 支持多图输入，提供多张参考图
              Collections.singletonMap("text", "把图2的涂鸦喷绘在图1的汽车上"),
              Collections.singletonMap("image", "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp"),
              Collections.singletonMap("image", "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp")
            )).build();
    
          ImageGenerationParam param = ImageGenerationParam.builder()
            .apiKey(apiKey)
            .model("wan2.7-image-pro")
            .n(1)
            .size("2K")
            .messages(Arrays.asList(message))
            .build();
    
          ImageGeneration imageGeneration = new ImageGeneration();
          ImageGenerationResult result = null;
          try {
            System.out.println("---异步调用图像编辑，正在创建任务----");
            result = imageGeneration.asyncCall(param);
          } catch (ApiException | NoApiKeyException | UploadFileException e) {
            throw new RuntimeException(e.getMessage());
          }
          System.out.println("任务创建结果:");
          System.out.println(JsonUtils.toJson(result));
    
          String taskId = result.getOutput().getTaskId();
          // 等待任务完成
          waitTask(taskId);
        }
    
        public static void waitTask(String taskId) throws ApiException, NoApiKeyException {
          ImageGeneration imageGeneration = new ImageGeneration();
          System.out.println("\n---等待任务完成----");
          ImageGenerationResult result = imageGeneration.wait(taskId, apiKey);
          System.out.println("任务完成结果:");
          System.out.println(JsonUtils.toJson(result));
        }
    
        public static void main(String[] args) {
          try {
            asyncCall();
          } catch (ApiException | NoApiKeyException | UploadFileException e) {
            System.out.println(e.getMessage());
          }
        }
      }
      ```
    
      ```json
      {
        "request_id": "4fb3050f-de57-4a24-84ff-e37ee5xxxxxx",
        "output": {
          "task_id": "127ec645-118f-4884-955d-0eba8dxxxxxx",
          "task_status": "PENDING"
        }
      }
      ```
    
      ```bash
      curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation' \
      --header 'Content-Type: application/json' \
      --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
      --header 'X-DashScope-Async: enable' \
      --data '{
        "model": "wan2.7-image-pro",
        "input": {
          "messages": [
            {
              "role": "user",
              "content": [
                {"image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp"},
                {"image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp"},
                {"text": "把图2的涂鸦喷绘在图1的汽车上"}
              ]
            }
          ]
        },
        "parameters": {
          "size": "2K",
          "n": 1,
          "watermark": false
        }
      }'
      ```
    
      ```json
      {
        "output": {
          "task_id": "127ec645-118f-4884-955d-0eba8dxxxxxx",
          "task_status": "PENDING"
        },
        "request_id": "4fb3050f-de57-4a24-84ff-e37ee5xxxxxx"
      }
      ```
    </CodeGroup>
  </Tab>
</Tabs>

<Accordion title="点击查看wan2.5-i2i-preview调用示例">
  wan2.5-i2i-preview使用不同的API端点和参数传入方式，其调用示例如下：

  ### 同步调用（wan2.5）

  <Note>请确保 DashScope Python SDK 版本不低于 `1.25.2`，DashScope Java SDK 版本不低于 `2.22.2`。</Note>

  <CodeGroup>
    ```python
    import base64
    import mimetypes
    from http import HTTPStatus
    from urllib.parse import urlparse, unquote
    from pathlib import PurePosixPath

    import dashscope
    import requests
    from dashscope import ImageSynthesis
    import os
    
    dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
    
    # 如果未设置环境变量，请将下行替换为：api_key="sk-xxx"
    api_key = os.getenv("DASHSCOPE_API_KEY")
    
    # --- 输入图片：Base64编码 ---
    # Base64格式：data:{MIME_type};base64,{base64_data}
    def encode_file(file_path):
      mime_type, _ = mimetypes.guess_type(file_path)
      if not mime_type or not mime_type.startswith("image/"):
        raise ValueError("不支持或无法识别的图片格式")
      with open(file_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
      return f"data:{mime_type};base64,{encoded_string}"
    
    """
    图像输入方式：
    选择以下其中一种：
    
    1. 公网URL — 适用于公开可访问的图片
    2. 本地文件 — 适用于本地开发和测试
    3. Base64编码 — 适用于私有图片或需要加密传输的场景
    """
    
    # [方式一] 公网图片URL
    image_url_1 = "https://img.alicdn.com/imgextra/i3/O1CN0157XGE51l6iL9441yX_!!6000000004770-49-tps-1104-1472.webp"
    image_url_2 = "https://img.alicdn.com/imgextra/i3/O1CN01SfG4J41UYn9WNt4X1_!!6000000002530-49-tps-1696-960.webp"
    
    # [方式二] 本地文件（支持绝对路径和相对路径）
    # 格式：file:// + 文件路径
    # 示例（绝对路径）：
    # image_url_1 = "file://" + "/path/to/your/image_1.png"     # Linux/macOS
    # image_url_2 = "file://" + "C:/path/to/your/image_2.png"  # Windows
    # 示例（相对路径）：
    # image_url_1 = "file://" + "./image_1.png"
    # image_url_2 = "file://" + "./image_2.png"
    
    # [方式三] Base64编码图片
    # image_url_1 = encode_file("./image_1.png")
    # image_url_2 = encode_file("./image_2.png")
    
    print('----同步调用，请稍候----')
    rsp = ImageSynthesis.call(api_key=api_key,
                              model="wan2.5-i2i-preview",
                              prompt="将图1中的闹钟放置到图2的餐桌的花瓶旁边位置",
                              images=[image_url_1, image_url_2],
                              negative_prompt="",
                              n=1,
                              # size="1280*1280",
                              prompt_extend=True,
                              watermark=False,
                              seed=12345)
    print('response: %s' % rsp)
    if rsp.status_code == HTTPStatus.OK:
      # 保存图片到当前目录
      for result in rsp.output.results:
        file_name = PurePosixPath(unquote(urlparse(result.url).path)).parts[-1]
        with open('./%s' % file_name, 'wb+') as f:
          f.write(requests.get(result.url).content)
    else:
      print('同步调用失败, status_code: %s, code: %s, message: %s' %
            (rsp.status_code, rsp.code, rsp.message))
    ```
    
    ```json
    {
        "status_code": 200,
        "request_id": "8ad45834-4321-44ed-adf5-xxxxxx",
        "code": null,
        "message": "",
        "output": {
            "task_id": "3aff9ebd-35fc-4339-98a3-xxxxxx",
            "task_status": "SUCCEEDED",
            "results": [
                {
                    "url": "https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx",
                    "orig_prompt": "将图1中的闹钟放置到图2的餐桌的花瓶旁边位置",
                    "actual_prompt": "将蓝色闹钟从图1放到图2餐桌花瓶右侧，靠近桌布边缘。保持闹钟面向镜头，平行于桌面，带自然投影。"
                }
            ],
            "submit_time": "2025-10-23 16:18:16.009",
            "scheduled_time": "2025-10-23 16:18:16.040",
            "end_time": "2025-10-23 16:19:09.591",
            "task_metrics": {
                "TOTAL": 1,
                "FAILED": 0,
                "SUCCEEDED": 1
            }
        },
        "usage": {
            "image_count": 1
        }
    }
    ```
    
    ```java
    // Copyright (c) Alibaba, Inc. and its affiliates.
    
    import com.alibaba.dashscope.aigc.imagesynthesis.ImageSynthesis;
    import com.alibaba.dashscope.aigc.imagesynthesis.ImageSynthesisParam;
    import com.alibaba.dashscope.aigc.imagesynthesis.ImageSynthesisResult;
    import com.alibaba.dashscope.exception.ApiException;
    import com.alibaba.dashscope.exception.NoApiKeyException;
    import com.alibaba.dashscope.utils.Constants;
    import com.alibaba.dashscope.utils.JsonUtils;
    
    import java.io.IOException;
    import java.nio.file.Files;
    import java.nio.file.Path;
    import java.nio.file.Paths;
    import java.util.*;
    
    public class Image2Image {
    
      static {
        Constants.baseHttpApiUrl = "https://dashscope.aliyuncs.com/api/v1";
      }
    
      // 如果未配置环境变量，请将下行替换为：apiKey="sk-xxx"
      static String apiKey = System.getenv("DASHSCOPE_API_KEY");
    
      /**
       * 图像输入方式：选择以下其中一种
       *
       * 1. 公网URL — 适用于公开可访问的图片
       * 2. 本地文件 — 适用于本地开发和测试
       * 3. Base64编码 — 适用于私有图片或需要加密传输的场景
       */
    
      // [方式一] 公网URL
      static String imageUrl_1 = "https://img.alicdn.com/imgextra/i3/O1CN0157XGE51l6iL9441yX_!!6000000004770-49-tps-1104-1472.webp";
      static String imageUrl_2 = "https://img.alicdn.com/imgextra/i3/O1CN01SfG4J41UYn9WNt4X1_!!6000000002530-49-tps-1696-960.webp";
    
      // [方式二] 本地文件路径（file://+绝对路径 或 file:///+绝对路径）
      // static String imageUrl_1 = "file://" + "/your/path/to/image_1.png";    // Linux/macOS
      // static String imageUrl_2 = "file:///" + "C:/your/path/to/image_2.png";  // Windows
    
      // [方式三] Base64编码
      // static String imageUrl_1 = encodeFile("/your/path/to/image_1.png");
      // static String imageUrl_2 = encodeFile("/your/path/to/image_2.png");
    
      // 待编辑的图片列表
      static List<String> imageUrls = new ArrayList<>();
      static {
        imageUrls.add(imageUrl_1);
        imageUrls.add(imageUrl_2);
      }
    
      public static void syncCall() {
        // 设置参数
        Map<String, Object> parameters = new HashMap<>();
        parameters.put("prompt_extend", true);
        parameters.put("watermark", false);
        parameters.put("seed", 12345);
    
        ImageSynthesisParam param =
          ImageSynthesisParam.builder()
            .apiKey(apiKey)
            .model("wan2.5-i2i-preview")
            .prompt("将图1中的闹钟放置到图2的餐桌的花瓶旁边位置")
            .images(imageUrls)
            .n(1)
             //.size("1280*1280")
            .negativePrompt("")
            .parameters(parameters)
            .build();
    
        ImageSynthesis imageSynthesis = new ImageSynthesis();
        ImageSynthesisResult result = null;
        try {
          System.out.println("---同步调用，请稍候----");
          result = imageSynthesis.call(param);
        } catch (ApiException | NoApiKeyException e){
          throw new RuntimeException(e.getMessage());
        }
        System.out.println(JsonUtils.toJson(result));
      }
    
      /**
       * 将文件编码为Base64字符串
       * @param filePath 文件路径
       * @return Base64字符串，格式为 data:{MIME_type};base64,{base64_data}
       */
      public static String encodeFile(String filePath) {
        Path path = Paths.get(filePath);
        if (!Files.exists(path)) {
          throw new IllegalArgumentException("文件不存在: " + filePath);
        }
        // 检测MIME类型
        String mimeType = null;
        try {
          mimeType = Files.probeContentType(path);
        } catch (IOException e) {
          throw new IllegalArgumentException("无法检测文件类型: " + filePath);
        }
        if (mimeType == null || !mimeType.startsWith("image/")) {
          throw new IllegalArgumentException("不支持或无法识别的图片格式");
        }
        // 读取文件并编码
        byte[] fileBytes = null;
        try{
          fileBytes = Files.readAllBytes(path);
        } catch (IOException e) {
          throw new IllegalArgumentException("无法读取文件: " + filePath);
        }
    
        String encodedString = Base64.getEncoder().encodeToString(fileBytes);
        return "data:" + mimeType + ";base64," + encodedString;
      }
    
      public static void main(String[] args) {
        syncCall();
      }
    }
    ```
    
    ```json
    {
        "request_id": "d362685b-757f-4eac-bab5-xxxxxx",
        "output": {
            "task_id": "bfa7fc39-3d87-4fa7-b1e6-xxxxxx",
            "task_status": "SUCCEEDED",
            "results": [
                {
                    "orig_prompt": "将图1中的闹钟放置到图2的餐桌的花瓶旁边位置",
                    "actual_prompt": "将蓝色闹钟从图1放到图2餐桌花瓶右侧，靠近桌布边缘。保持闹钟面向镜头，平行于花瓶。",
                    "url": "https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx"
                }
            ],
            "task_metrics": {
                "TOTAL": 1,
                "SUCCEEDED": 1,
                "FAILED": 0
            }
        },
        "usage": {
            "image_count": 1
        }
    }
    ```
  </CodeGroup>

  ### 异步调用（wan2.5）

  <Note>请确保 DashScope Python SDK 版本不低于 `1.25.2`，DashScope Java SDK 版本不低于 `2.22.2`。</Note>

  <CodeGroup>
    ```python
    import os
    from http import HTTPStatus
    from urllib.parse import urlparse, unquote
    from pathlib import PurePosixPath
    import dashscope
    import requests
    from dashscope import ImageSynthesis

    dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
    
    # 如果未设置环境变量，请将下行替换为：api_key="sk-xxx"
    api_key = os.getenv("DASHSCOPE_API_KEY")
    
    # 公网图片URL
    image_url_1 = "https://img.alicdn.com/imgextra/i3/O1CN0157XGE51l6iL9441yX_!!6000000004770-49-tps-1104-1472.webp"
    image_url_2 = "https://img.alicdn.com/imgextra/i3/O1CN01SfG4J41UYn9WNt4X1_!!6000000002530-49-tps-1696-960.webp"
    
    def async_call():
      print('----创建任务----')
      task_info = create_async_task()
      print('----等待任务----')
      wait_async_task(task_info)
    
    # 创建异步任务
    def create_async_task():
      rsp = ImageSynthesis.async_call(api_key=api_key,
                                      model="wan2.5-i2i-preview",
                                      prompt="将图1中的闹钟放置到图2的餐桌的花瓶旁边位置",
                                      images=[image_url_1, image_url_2],
                                      negative_prompt="",
                                      n=1,
                                      # size="1280*1280",
                                      prompt_extend=True,
                                      watermark=False,
                                      seed=12345)
      print(rsp)
      if rsp.status_code == HTTPStatus.OK:
        print(rsp.output)
      else:
        print('失败, status_code: %s, code: %s, message: %s' %
              (rsp.status_code, rsp.code, rsp.message))
      return rsp
    
    # 等待异步任务完成
    def wait_async_task(task):
      rsp = ImageSynthesis.wait(task=task, api_key=api_key)
      print(rsp)
      if rsp.status_code == HTTPStatus.OK:
        print(rsp.output)
        # 保存文件到当前目录
        for result in rsp.output.results:
          file_name = PurePosixPath(unquote(urlparse(result.url).path)).parts[-1]
          with open('./%s' % file_name, 'wb+') as f:
            f.write(requests.get(result.url).content)
      else:
        print('失败, status_code: %s, code: %s, message: %s' %
              (rsp.status_code, rsp.code, rsp.message))
    
    # 查询异步任务状态
    def fetch_task_status(task):
      status = ImageSynthesis.fetch(task=task, api_key=api_key)
      print(status)
      if status.status_code == HTTPStatus.OK:
        print(status.output.task_status)
      else:
        print('失败, status_code: %s, code: %s, message: %s' %
              (status.status_code, status.code, status.message))
    
    # 取消异步任务，仅PENDING状态的任务可以取消
    def cancel_task(task):
      rsp = ImageSynthesis.cancel(task=task, api_key=api_key)
      print(rsp)
      if rsp.status_code == HTTPStatus.OK:
        print(rsp.output.task_status)
      else:
        print('失败, status_code: %s, code: %s, message: %s' %
              (rsp.status_code, rsp.code, rsp.message))
    
    if __name__ == '__main__':
      async_call()
    ```
    
    ```json
    {
        "status_code": 200,
        "request_id": "31b04171-011c-96bd-ac00-f0383b669cc7",
        "code": "",
        "message": "",
        "output": {
            "task_id": "4f90cf14-a34e-4eae-xxxxxxxx",
            "task_status": "PENDING",
            "results": []
        },
        "usage": null
    }
    ```
    
    ```json
    {
        "status_code": 200,
        "request_id": "8ad45834-4321-44ed-adf5-xxxxxx",
        "code": null,
        "message": "",
        "output": {
            "task_id": "3aff9ebd-35fc-4339-98a3-xxxxxx",
            "task_status": "SUCCEEDED",
            "results": [
                {
                    "url": "https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx",
                    "orig_prompt": "将图1中的闹钟放置到图2的餐桌的花瓶旁边位置",
                    "actual_prompt": "将蓝色闹钟从图1放到图2餐桌花瓶右侧，靠近桌布边缘。保持闹钟面向镜头，平行于桌面，带自然投影。"
                }
            ],
            "submit_time": "2025-10-23 16:18:16.009",
            "scheduled_time": "2025-10-23 16:18:16.040",
            "end_time": "2025-10-23 16:19:09.591",
            "task_metrics": {
                "TOTAL": 1,
                "FAILED": 0,
                "SUCCEEDED": 1
            }
        },
        "usage": {
            "image_count": 1
        }
    }
    ```
    
    ```java
    // Copyright (c) Alibaba, Inc. and its affiliates.
    
    import com.alibaba.dashscope.aigc.imagesynthesis.ImageSynthesis;
    import com.alibaba.dashscope.aigc.imagesynthesis.ImageSynthesisListResult;
    import com.alibaba.dashscope.aigc.imagesynthesis.ImageSynthesisParam;
    import com.alibaba.dashscope.aigc.imagesynthesis.ImageSynthesisResult;
    import com.alibaba.dashscope.exception.ApiException;
    import com.alibaba.dashscope.exception.NoApiKeyException;
    import com.alibaba.dashscope.task.AsyncTaskListParam;
    import com.alibaba.dashscope.utils.Constants;
    import com.alibaba.dashscope.utils.JsonUtils;
    
    import java.util.ArrayList;
    import java.util.HashMap;
    import java.util.List;
    import java.util.Map;
    
    public class Image2Image {
    
      static {
        Constants.baseHttpApiUrl = "https://dashscope.aliyuncs.com/api/v1";
      }
    
      // 如果未配置环境变量，请将下行替换为：apiKey="sk-xxx"
      static String apiKey = System.getenv("DASHSCOPE_API_KEY");
    
      // 公网URL
      static String imageUrl_1 = "https://img.alicdn.com/imgextra/i3/O1CN0157XGE51l6iL9441yX_!!6000000004770-49-tps-1104-1472.webp";
      static String imageUrl_2 = "https://img.alicdn.com/imgextra/i3/O1CN01SfG4J41UYn9WNt4X1_!!6000000002530-49-tps-1696-960.webp";
    
      // 待编辑的图片列表
      static List<String> imageUrls = new ArrayList<>();
      static {
        imageUrls.add(imageUrl_1);
        imageUrls.add(imageUrl_2);
      }
    
      public static void asyncCall() {
        // 设置参数
        Map<String, Object> parameters = new HashMap<>();
        parameters.put("prompt_extend", true);
        parameters.put("watermark", false);
        parameters.put("seed", 12345);
    
        ImageSynthesisParam param =
          ImageSynthesisParam.builder()
            .apiKey(apiKey)
            .model("wan2.5-i2i-preview")
            .prompt("将图1中的闹钟放置到图2的餐桌的花瓶旁边位置")
            .images(imageUrls)
            .n(1)
            //.size("1280*1280")
            .negativePrompt("")
            .parameters(parameters)
            .build();
        ImageSynthesis imageSynthesis = new ImageSynthesis();
        ImageSynthesisResult result = null;
        try {
          System.out.println("---异步调用，请稍候----");
          result = imageSynthesis.asyncCall(param);
        } catch (ApiException | NoApiKeyException e){
          throw new RuntimeException(e.getMessage());
        }
    
        System.out.println(JsonUtils.toJson(result));
    
        String taskId = result.getOutput().getTaskId();
    
        System.out.println("taskId=" + taskId);
    
        try {
          result = imageSynthesis.wait(taskId, apiKey);
        } catch (ApiException | NoApiKeyException e){
          throw new RuntimeException(e.getMessage());
        }
        System.out.println(JsonUtils.toJson(result));
        System.out.println(JsonUtils.toJson(result.getOutput()));
      }
    
      public static void listTask() throws ApiException, NoApiKeyException {
        ImageSynthesis is = new ImageSynthesis();
        AsyncTaskListParam param = AsyncTaskListParam.builder().build();
        param.setApiKey(apiKey);
        ImageSynthesisListResult result = is.list(param);
        System.out.println(result);
      }
    
      public void fetchTask(String taskId) throws ApiException, NoApiKeyException {
        ImageSynthesis is = new ImageSynthesis();
        // 如果已设置 DASHSCOPE_API_KEY 环境变量，apiKey 可以为空
        ImageSynthesisResult result = is.fetch(taskId, apiKey);
        System.out.println(result.getOutput());
        System.out.println(result.getUsage());
      }
    
      public static void main(String[] args) {
        asyncCall();
      }
    }
    ```
    
    ```json
    {
        "request_id": "5dbf9dc5-4f4c-9605-85ea-542f97709ba8",
        "output": {
            "task_id": "7277e20e-aa01-4709-xxxxxxxx",
            "task_status": "PENDING"
        }
    }
    ```
    
    ```json
    {
        "request_id": "d362685b-757f-4eac-bab5-xxxxxx",
        "output": {
            "task_id": "bfa7fc39-3d87-4fa7-b1e6-xxxxxx",
            "task_status": "SUCCEEDED",
            "results": [
                {
                    "orig_prompt": "将图1中的闹钟放置到图2的餐桌的花瓶旁边位置",
                    "actual_prompt": "将蓝色闹钟从图1放到图2餐桌花瓶右侧，靠近桌布边缘。保持闹钟面向镜头，平行于花瓶。",
                    "url": "https://dashscope-result-sh.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx"
                }
            ],
            "task_metrics": {
                "TOTAL": 1,
                "SUCCEEDED": 1,
                "FAILED": 0
            }
        },
        "usage": {
            "image_count": 1
        }
    }
    ```
  </CodeGroup>
</Accordion>

## 模型选型

- **wan2.7-image-pro、wan2.7-image**（推荐）：适合对编辑精度要求高、或需要生成多张内容连贯图像的场景。

  - [精准局部编辑](#4-交互式精准编辑)：框选图中指定区域，对该区域的对象进行移动、替换或添加新元素，适用于电商修图、设计稿调整。

  - 多格连续图生成：一次输出多张风格统一的图像，适用于漫画分镜、产品系列图、故事连环图。

- **wan2.6-image**：适合图文混排或带多张参考图的风格化编辑场景，支持在生成图像时生成对应文字内容，最多支持 4 张参考图输入。

- **wan2.5-i2i-preview**：适合简单的图像编辑和多图融合。

各模型的输入和输出规格见[输入图像规格](#输入图像规格)和[设置输出图像分辨率](#3-设置输出图像分辨率)。

## 效果展示

### 图生组图

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "40%", paddingBottom: "8px"}}>输入图像</th>
      <th style={{textAlign: "left", width: "60%", paddingBottom: "8px"}}>输出图像</th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="输入人像" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1064359.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top"}}>
        <img alt="output" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1064360.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>
    </tr>
  </tbody>
</table>

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <tbody>
    <tr>
      <td style={{verticalAlign: "top", width: "33%"}}>
        <img alt="输入人像2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1064362.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top", width: "67%"}}>
        <img alt="output" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1064361.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>
    </tr>
  </tbody>
</table>

### 交互式编辑

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "70%", paddingBottom: "8px"}}>输入图像</th>
      <th style={{textAlign: "left", width: "30%", paddingBottom: "8px"}}>输出图像</th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="交互式编辑输入2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/8163205771/p1064355.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top"}}>
        <img alt="交互式编辑输出2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1064356.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        将图1中框选的图案放置到图二中框选处
      </td>
    </tr>
  </tbody>
</table>

### 多图融合

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "69%", paddingBottom: "8px"}}>输入图像</th>
      <th style={{textAlign: "left", width: "31%", paddingBottom: "8px"}}>输出图像</th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="多图融合输入1" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039962.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top"}}>
        <img alt="多图融合输出1" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039963.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        给图1的男生和图2的狗拍一张写真，男生搂着这只狗，人和狗都很开心，摄影棚柔和灯光，蓝色纹理背景
      </td>
    </tr>
  </tbody>
</table>

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <tbody>
    <tr>
      <td style={{verticalAlign: "top", width: "75%"}}>
        <img alt="多图融合输入2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039968.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top", width: "25%"}}>
        <img alt="多图融合输出2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039971.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        给图1的裙子按照图2鸟的颜色进行配色，充满艺术感，衣服款式不变，模特不变
      </td>
    </tr>
  </tbody>
</table>

### 主体特征保持

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "50%", paddingBottom: "8px"}}>输入图像</th>
      <th style={{textAlign: "left", width: "50%", paddingBottom: "8px"}}>输出图像</th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="主体特征保持输入2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/8163205771/p1040012.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top"}}>
        <img alt="主体特征保持输出2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1040013.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>
    </tr>
  </tbody>
</table>

### 检测和分割

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "50%", paddingBottom: "8px"}}>输入图像</th>
      <th style={{textAlign: "left", width: "50%", paddingBottom: "8px"}}>输出图像</th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="检测分割输入1" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1040006.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top"}}>
        <img alt="检测分割输出1" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1040007.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        检测图片中的笔记本电脑和闹钟，画框并标注"laptop"和"clock"
      </td>
    </tr>
    
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="检测分割输入2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1040008.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>
    
      <td style={{verticalAlign: "top"}}>
        <img alt="检测分割输出2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1040009.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        分割图片中的玻璃杯
      </td>
    </tr>
  </tbody>
</table>

### 提取元素

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "33%", paddingBottom: "8px"}}>输入图像</th>
      <th style={{textAlign: "left", width: "67%", paddingBottom: "8px"}}>输出图像</th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="提取元素输入" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1040000.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top"}}>
        <img alt="提取元素输出" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1040001.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        从上传照片中提取穿搭单品，将它们以平铺展示的方式排列在纯白背景上，保持真实细节与材质质感，时尚电商风格，适合服装展示。
      </td>
    </tr>
  </tbody>
</table>

### 文本编辑

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "50%", paddingBottom: "8px"}}>输入图像</th>
      <th style={{textAlign: "left", width: "50%", paddingBottom: "8px"}}>输出图像</th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="文本编辑输入1" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/8163205771/p1039976.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top"}}>
        <img alt="文本编辑输出1" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039977.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        去除全图水印
      </td>
    </tr>
    
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="文本编辑输入2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039978.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>
    
      <td style={{verticalAlign: "top"}}>
        <img alt="文本编辑输出2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039979.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        用手在沙滩上随意的写上"Time for Holiday?"
      </td>
    </tr>
    
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="文本编辑输入3" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039980.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>
    
      <td style={{verticalAlign: "top"}}>
        <img alt="文本编辑输出3" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039981.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        把18改成29，把JUNE改成SEPTEMBER
      </td>
    </tr>
  </tbody>
</table>

### 镜头与视角编辑

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "50%", paddingBottom: "8px"}}>输入图像</th>
      <th style={{textAlign: "left", width: "50%", paddingBottom: "8px"}}>输出图像</th>
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="镜头编辑输入1" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039991.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>

      <td style={{verticalAlign: "top"}}>
        <img alt="镜头编辑输出1" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039992.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        保持人物的特征不变，生成正视图、侧视图和背视图
      </td>
    </tr>
    
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="镜头编辑输入2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/9163205771/p1039995.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
      </td>
    
      <td style={{verticalAlign: "top"}}>
        <img alt="镜头编辑输出2" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/8163205771/p1039996.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        用鱼眼镜头重新拍摄这张照片
      </td>
    </tr>
  </tbody>
</table>

## 输入说明

### 输入图像规格

| **规格**     | **wan2.7-image-pro、wan2.7-image**          | **wan2.6-image**                            | **wan2.5-i2i-preview**                      |
| ------------ | ------------------------------------------- | ------------------------------------------- | ------------------------------------------- |
| 输入图像数量 | 0～9 张（0张对应文生图模式）                | 图像编辑 1～4 张 / 图文混排 0～1 张         | 1～3 张                                     |
| 图片格式     | JPEG、JPG、PNG（不支持透明通道）、BMP、WEBP | JPEG、JPG、PNG（不支持透明通道）、BMP、WEBP | JPEG、JPG、PNG（不支持透明通道）、BMP、WEBP |
| 图片宽高范围 | \[240, 8000] 像素                           | \[240, 8000] 像素                           | \[384, 5000] 像素                           |
| 文件大小     | ≤ 20MB                                      | ≤ 10MB                                      | ≤ 10MB                                      |
| 宽高比       | \[1:8, 8:1]                                 | 不限                                        | \[1:4, 4:1]                                 |

### 图像输入顺序

多图输入时，按照数组中的顺序定义图像顺序。因此，提示词引用的图像编号需要**与图像数组中的顺序一一对应**，例如：数组中的第一张图片为"图1"，第二张为"图2"，或者使用标记形式如"\[图1]"、"\[图2]"。

```json
{
    "content": [
        {"text": "编辑指令，如：将图1中的闹钟放置到图2的餐桌的花瓶旁边位置"},
        {"image": "https://example.com/image1.png"},
        {"image": "https://example.com/image2.png"}
    ]
}
```

<table style={{width: "100%", borderCollapse: "separate", borderSpacing: "8px 0", tableLayout: "fixed"}}>
  <thead>
    <tr>
      <th style={{textAlign: "left", width: "27%", paddingBottom: "8px"}}>**输入图像1**</th>
      <th style={{textAlign: "left", width: "20%", paddingBottom: "8px"}}>**输入图像2**</th>
      <th style={{textAlign: "left", width: "27%", paddingBottom: "8px"}}>**输出图像**</th>

      <th style={{textAlign: "left", width: "27%", paddingBottom: "8px"}} />
    </tr>
  </thead>

  <tbody>
    <tr>
      <td style={{verticalAlign: "top"}}>
        <img alt="image (19)-转换自-png" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/3509593671/p1025838.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />

        图1
      </td>
    
      <td style={{verticalAlign: "top"}}>
        <img alt="image (20)-转换自-png" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/3509593671/p1025839.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        图2
      </td>
    
      <td style={{verticalAlign: "top"}}>
        <img alt="04e0fc39-7ad6-41e0-9df9-1f69ac3ce825-转换自-png" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/3509593671/p1021092.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        提示词：把图1移动到图2上
      </td>
    
      <td style={{verticalAlign: "top"}}>
        <img alt="36ed450d-bd54-4169-b13f-3d0f26d9d360-转换自-png" src="https://help-static-aliyun-doc.aliyuncs.com/assets/img/en-US/3509593671/p1021093.webp" style={{display: "block", width: "100%", margin: "0 0 8px 0"}} />
    
        提示词：把图2移动到图1上
      </td>
    </tr>
  </tbody>
</table>

### 图像传入方式

支持通过以下方式传入图像：

<Accordion title="方式一：公网URL">
  ```python
  # 使用公网可访问的图片URL
  image_url = "https://example.com/your-image.png"
  ```

  ```bash
  # 在curl中，直接在JSON body中传入URL
  "image": "https://example.com/your-image.png"
  ```
</Accordion>

<Accordion title="方式二：Base64编码">
  ```python
  import os
  import base64
  import mimetypes

  # 格式为 data:{mime_type};base64,{base64_data}
  def encode_file(file_path):
    mime_type, _ = mimetypes.guess_type(file_path)
    with open(file_path, "rb") as image_file:
      encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return f"data:{mime_type};base64,{encoded_string}"

  # 调用编码函数，请将 "/path/to/your/image.png" 替换为您的本地图片文件路径，否则无法运行
  image = encode_file("/path/to/your/image.png")
  ```
</Accordion>

<Accordion title="方式三：本地文件路径（仅限SDK）">
  ```python
  # 本地文件路径格式：file:// + 绝对路径
  # Linux/macOS 示例：
  image_url = "file://" + "/path/to/your/image.png"
  # Windows 示例：
  image_url = "file:///" + "C:/path/to/your/image.png"

  # 相对路径示例：
  image_url = "file://" + "./your-image.png"
  ```

  此方式仅支持 SDK 调用。curl 请求需使用公网URL或Base64编码。
</Accordion>

## 关键能力

### 1. 指令遵循（提示词）

参数：`messages.content.text`或`input.prompt`（必选）、`negative_prompt`（可选）。

| **参数**         | **wan2.7-image-pro、wan2.7-image** | **wan2.6-image**   | **wan2.5-i2i-preview** |
| ---------------- | ---------------------------------- | ------------------ | ---------------------- |
| text             | 必选，最多5000字符                 | 必选，最多2000字符 | 不支持                 |
| prompt           | 不支持                             | 不支持             | 必选，最多2000字符     |
| negative\_prompt | 不支持                             | 支持，最多500字符  | 支持，最多500字符      |

### 2. 开启prompt智能改写

参数：`parameters.prompt_extend`（bool，**默认为 true**）。

此功能可自动扩展和优化较短的Prompt，提升输出图像效果。开启此功能会增加额外耗时。

| **参数**       | **wan2.7-image-pro、wan2.7-image** | **wan2.6-image**       | **wan2.5-i2i-preview** |
| -------------- | ---------------------------------- | ---------------------- | ---------------------- |
| prompt\_extend | 不支持                             | 支持（仅图像编辑模式） | 支持                   |

### 3. 设置输出图像分辨率

参数：`parameters.size`（string），格式为`"宽*高"`。

| **参数** | **wan2.7-image-pro、wan2.7-image**                           | **wan2.6-image**                                             | **wan2.5-i2i-preview**                                       |
| -------- | ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| size     | **方式一：指定输出图片的分辨率（推荐）** 编辑模式（传入至少一张图片），可选的输出分辨率档位：`1K`、`2K`（默认）。`1K`：输出总像素接近 1024\*1024，宽高比与最后一张输入图像一致。`2K`：输出总像素接近 2048\*2048，宽高比与最后一张输入图像一致。**方式二：指定生成图像的宽高像素值** 总像素在 \[768\*768, 2048\*2048] 之间，宽高比范围为 \[1:8, 8:1]。仅文生图场景的 wan2.7-image-pro 支持 4K 分辨率。 | **方式一：参考输入图比例（推荐）** 编辑模式（`enable_interleave=false`），可选的输出分辨率档位：`1K`（默认）、`2K`。`1K`：输出总像素接近 1280\*1280，宽高比与最后一张输入图像一致。`2K`：输出总像素接近 2048\*2048，宽高比与最后一张输入图像一致。**方式二：指定生成图像的宽高像素值** 总像素在 \[768\*768, 2048\*2048] 之间，宽高比范围为 \[1:4, 4:1]。实际输出图像的像素值为接近指定值的16的倍数。 | **仅支持指定生成图像的宽高像素值** 总像素在 \[768\*768, 1280\*1280] 之间，宽高比范围为 \[1:4, 4:1]。若未指定`size`，系统将默认生成总像素为 `1280*1280` 的图像，宽高比与最后一张输入图像一致。 |

### 4. 交互式精准编辑

通过 `parameters.bbox_list` 参数框选图中需要编辑的物品或位置，实现更准确的编辑效果。**仅 wan2.7-image-pro、wan2.7-image 支持此功能。**

- 对应关系：列表长度必须与输入图片数量一致。若某张图片无需编辑，需要在对应位置传入空列表 `[]`。
- 坐标格式：`[x1, y1, x2, y2]`（左上角 x, 左上角 y, 右下角 x, 右下角 y），使用原图绝对像素坐标，左上角对应（0，0），x 轴向右，y 轴向下。
- 数量限制：单张图片最多支持 2 个边界框。

示例：输入 3 张图片，其中第 2 张无框选，第 1 张有两个框选：

```json
[
  [[0, 0, 12, 12], [25, 25, 100, 100]],
  [],
  [[10, 10, 50, 50]]
]
```

<Accordion title="如何确定编辑区域坐标">
  **方法一：OpenCV 画框**

  在图片上拖拽鼠标画框，精准直观：

  ```python
  # 安装依赖：pip install opencv-python
  import cv2
  import urllib.request

  # 下载示例图片（替换为您自己的图片 URL 或本地路径）
  image_url = "https://img.alicdn.com/imgextra/i3/O1CN01SfG4J41UYn9WNt4X1_!!6000000002530-49-tps-1696-960.webp"
  urllib.request.urlretrieve(image_url, "example.webp")

  # 读取图片并弹出交互窗口
  img = cv2.imread("example.webp")
  # 在弹出的窗口中用鼠标拖拽画框，按 Enter 确认选区，按 Esc 取消
  x, y, w, h = cv2.selectROI("Draw bounding box (Enter=confirm, Esc=cancel)", img)
  cv2.destroyAllWindows()

  # 将 OpenCV 返回的 (x, y, w, h) 转换为 bbox_list 所需的 [x1, y1, x2, y2] 格式
  bbox = [x, y, x + w, y + h]
  print(f"框选坐标: {bbox}")
  ```

  **方法二：视觉理解模型**

  通过 qwen3.7-plus 自动识别目标区域坐标，用自然语言描述目标即可获取坐标：

  ````python
  # 安装依赖：pip install dashscope pillow
  import os
  import json
  from dashscope import MultiModalConversation
  import dashscope
  from PIL import Image
  import urllib.request

  dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"

  def get_bbox_list(image, prompt):
    """
    通过 qwen3.7-plus 识别图片中的目标区域，返回绝对像素坐标列表。
    """
    full_prompt = (
      prompt + "\n"
      "请根据以上描述，返回对应区域的坐标。\n"
      "最多返回2个区域，优先返回最匹配的目标。\n"
      "严格按照JSON二维列表格式返回：[[x1, y1, x2, y2], ...]\n"
      "每组坐标：[左上角x, 左上角y, 右下角x, 右下角y]\n"
      "使用原图绝对像素坐标，左上角为(0,0)，x轴向右，y轴向下。\n"
      "如果只有一个区域，也必须使用二维列表：[[x1, y1, x2, y2]]\n"
      "只返回JSON列表，不要返回其他任何内容。"
    )

    messages = [
      {'role': 'user',
       'content': [
         {'image': image},
         {'text': full_prompt}
       ]}
    ]

    response = MultiModalConversation.call(
      api_key=os.getenv('DASHSCOPE_API_KEY'),
      model='qwen3.7-plus',
      messages=messages,
    )

    text = response.output.choices[0].message.content[0]["text"]
    text = text.replace("```json", "").replace("```", "").strip()
    coords = json.loads(text)

    if coords and not isinstance(coords[0], list):
      coords = [coords]

    # 获取图片尺寸，用于坐标转换
    if image.startswith("file://"):
      local_path = image[len("file://"):]
      img = Image.open(local_path)
    else:
      tmp_path = "temp_bbox_image"
      urllib.request.urlretrieve(image, tmp_path)
      img = Image.open(tmp_path)
    width, height = img.size

    # 模型返回归一化坐标 [0, 999]，转换为绝对像素坐标
    bbox_list = []
    for box in coords:
      bbox_list.append([
        int(box[0] / 1000 * width),
        int(box[1] / 1000 * height),
        int(box[2] / 1000 * width),
        int(box[3] / 1000 * height)
      ])

    return bbox_list

  # === 使用示例 ===
  image_url = "https://img.alicdn.com/imgextra/i3/O1CN01ewUWhg1eS3VqJ3wap_!!6000000003869-49-tps-2048-2048.webp"

  # 按名称选取目标
  bbox = get_bbox_list(image_url, "咖啡杯")

  # 按位置描述选取目标
  bbox = get_bbox_list(image_url, "盘子正中间的水果")
  ````
</Accordion>

## 计费与限流

- 模型免费额度和计费单价请参见[模型列表与价格](/developer-guides/getting-started/pricing)。

- 模型限流请参见[限流](/developer-guides/administration/rate-limits)。

- 计费说明：
  - 按成功生成的**图像张数**计费。仅当接口返回`task_status`为`SUCCEEDED`并成功生成图像后，才会计费。
  - 模型调用失败或处理错误不产生任何费用，也不消耗[免费额度](/resources/free-quota)。

## API参考

各模型使用不同的端点和请求结构：

| **模型**                                           | **端点**                                                     |
| -------------------------------------------------- | ------------------------------------------------------------ |
| `wan2.7-image`、`wan2.7-image-pro`、`wan2.6-image` | 同步接口：`POST https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`<br />异步接口：`POST https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation` |
| `wan2.5-i2i-preview`                               | 异步接口：`POST https://dashscope.aliyuncs.com/api/v1/services/aigc/image2image/image-synthesis` |

- `wan2.7` / `wan2.6`：`messages` 格式，在 `messages[].content` 数组中，通过 `image` 传入图像，通过 `text` 传入提示词。
- `wan2.5`：通过 `input.images` 数组传入图像，通过 `input.prompt` 传入提示词。

输入和输出参数请参见 [Wan 2.7 API参考](/api-reference/image-generation/wan27-image-gen-edit/create-task)、[Wan 2.6 API参考](/api-reference/image-generation/wan26-image-gen-edit/create-task) 和 [Wan 2.5 API参考](/api-reference/image-generation/wan25-general-image-editing/create-task)。







> ## Documentation Index
>
> Fetch the complete documentation index at: https://platform.qianwenai.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Wan 2.7 — 同步调用

> Wan 2.7 同步图像生成与编辑

<Note>
  [获取 API Key](/api-reference/preparation/api-key) 并[设置为环境变量](/api-reference/preparation/export-api-key-env)。如需使用 SDK，请先[安装 SDK](/api-reference/preparation/install-sdk)。
</Note>

该同步接口支持 **wan2.7-image-pro** 和 **wan2.7-image** 模型。通过单次请求即可直接获取生成的图像，无需轮询。

如需异步处理，请使用[异步提交](/api-reference/image-generation/wan27-image-gen-edit/create-task)接口。

## OpenAPI

````yaml post /services/aigc/multimodal-generation/generation
openapi: 3.1.0
info:
  title: Wan2.7 图像生成与编辑 API
  description: Wan2.7 图像生成与编辑 API，支持文生图、多图编辑、边界框交互式编辑以及图像集生成。
  version: 1.0.0
servers:
  - url: https://dashscope.aliyuncs.com/api/v1
    description: 北京
security:
  - BearerAuth: []
paths:
  /services/aigc/multimodal-generation/generation:
    post:
      operationId: createWan27Image
      summary: 同步生成或编辑图像
      description: 使用 Wan2.7 同步生成或编辑图像。支持文生图、多图编辑、边界框交互式编辑和图像集生成。
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/Wan27ImageRequest"
      responses:
        "200":
          description: 图像已成功生成或编辑
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Wan27ImageResponse"
        "400":
          description: 请求参数无效
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/DashScopeErrorResponse"
      x-codeSamples:
        - lang: curl
          label: cURL (text-to-image)
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation' \
            --header 'Content-Type: application/json' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --data '{
              "model": "wan2.7-image-pro",
              "input": {
                "messages": [
                  {
                    "role": "user",
                    "content": [
                      {
                        "text": "A serene mountain lake at sunrise, with mist rising from the water, surrounded by pine trees, photorealistic"
                      }
                    ]
                  }
                ]
              },
              "parameters": {
                "n": 1,
                "size": "2K",
                "watermark": false,
                "thinking_mode": true
              }
            }'
        - lang: curl
          label: cURL (image editing)
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation' \
            --header 'Content-Type: application/json' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --data '{
              "model": "wan2.7-image-pro",
              "input": {
                "messages": [
                  {
                    "role": "user",
                    "content": [
                      {
                        "image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp"
                      },
                      {
                        "image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp"
                      },
                      {
                        "text": "Spray the graffiti from image 2 onto the car in image 1"
                      }
                    ]
                  }
                ]
              },
              "parameters": {
                "n": 1,
                "size": "2K",
                "watermark": false
              }
            }'
        - lang: curl
          label: cURL (interactive editing)
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation' \
            --header 'Content-Type: application/json' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --data '{
              "model": "wan2.7-image-pro",
              "input": {
                "messages": [
                  {
                    "role": "user",
                    "content": [
                      {
                        "image": "https://img.alicdn.com/imgextra/i3/O1CN0157XGE51l6iL9441yX_!!6000000004770-49-tps-1104-1472.webp"
                      },
                      {
                        "image": "https://img.alicdn.com/imgextra/i3/O1CN01SfG4J41UYn9WNt4X1_!!6000000002530-49-tps-1696-960.webp"
                      },
                      {
                        "text": "Place the alarm clock from image 1 in the selected area of image 2, ensuring the scene and lighting blend naturally"
                      }
                    ]
                  }
                ]
              },
              "parameters": {
                "n": 1,
                "size": "2K",
                "watermark": false,
                "bbox_list": [[], [[989, 515, 1138, 681]]]
              }
            }'
        - lang: curl
          label: cURL (image set generation)
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation' \
            --header 'Content-Type: application/json' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --data '{
              "model": "wan2.7-image-pro",
              "input": {
                "messages": [
                  {
                    "role": "user",
                    "content": [
                      {
                        "text": "Cinematic image group, documenting the same stray orange cat, features must be consistent throughout. First image: Spring, an orange cat walks under blooming cherry trees; Second image: Summer, an orange cat rests in the shade of an old street to escape the heat; Third image: Autumn, an orange cat walks on golden fallen leaves; Fourth image: Winter, an orange cat walks on snow, leaving paw prints."
                      }
                    ]
                  }
                ]
              },
              "parameters": {
                "enable_sequential": true,
                "n": 4,
                "size": "2K"
              }
            }'
        - lang: python
          label: Python - image editing (sync)
          source: |-
            import os
            import base64
            import mimetypes
            import dashscope
            from dashscope.aigc.image_generation import ImageGeneration
            from dashscope.api_entities.dashscope_response import Message

            # 需要 SDK 版本 >= 1.25.15
            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

            api_key = os.getenv("DASHSCOPE_API_KEY")

            def encode_file(file_path):
              mime_type, _ = mimetypes.guess_type(file_path)
              if not mime_type or not mime_type.startswith("image/"):
                raise ValueError("Unsupported or unrecognized image format")
              with open(file_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
              return f"data:{mime_type};base64,{encoded_string}"

            # 图片输入支持三种方式：公开 URL、本地文件路径、Base64 编码
            image_1 = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp"
            image_2 = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp"
            # image_1 = "file:///path/to/your/car.png"
            # image_1 = encode_file("/path/to/your/car.png")

            message = Message(
              role="user",
              content=[
                {"text": "Spray the graffiti from image 2 onto the car in image 1"},
                {"image": image_1},
                {"image": image_2}
              ]
            )

            print("----sync call, please wait a moment----")
            rsp = ImageGeneration.call(
              model='wan2.7-image-pro',
              api_key=api_key,
              messages=[message],
              n=1,
              # wan2.7-image-pro 文生图支持 1K、2K 或 4K；
              # 图像编辑和图像集生成最高支持 2K
              size="2K",
              watermark=False
            )

            print(rsp)
        - lang: python
          label: Python - image set generation (sync)
          source: |-
            import os
            import base64
            import mimetypes
            import dashscope
            from dashscope.aigc.image_generation import ImageGeneration
            from dashscope.api_entities.dashscope_response import Message

            # 需要 SDK 版本 >= 1.25.15
            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

            api_key = os.getenv("DASHSCOPE_API_KEY")

            def encode_file(file_path):
              mime_type, _ = mimetypes.guess_type(file_path)
              if not mime_type or not mime_type.startswith("image/"):
                raise ValueError("Unsupported or unrecognized image format")
              with open(file_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
              return f"data:{mime_type};base64,{encoded_string}"

            # 文生图像集（默认）
            message = Message(
              role="user",
              content=[
                {"text": "Cinematic image group, documenting the same stray orange cat, features must be consistent throughout. First image: Spring, an orange cat walks under blooming cherry trees; Second image: Summer, an orange cat rests in the shade of an old street to escape the heat; Third image: Autumn, an orange cat walks on golden fallen leaves; Fourth image: Winter, an orange cat walks on snow, leaving paw prints."}
              ]
            )

            # 图生图像集（取消注释后使用）
            # 图片输入支持三种方式：公开 URL、本地文件路径、Base64 编码
            # image_1 = "https://example.com/your-image.png"
            # image_1 = "file:///path/to/your/image.png"
            # image_1 = encode_file("/path/to/your/image.png")
            # message = Message(
            #   role="user",
            #   content=[
            #     {"text": "Generate a sequential image set based on the input image"},
            #     {"image": image_1}
            #   ]
            # )

            print("----sync call, please wait a moment----")
            rsp = ImageGeneration.call(
              model='wan2.7-image-pro',
              api_key=api_key,
              messages=[message],
              enable_sequential=True,
              n=4,
              # wan2.7-image-pro 文生图支持 1K、2K 或 4K；
              # 图像编辑和图像集生成最高支持 2K
              size="2K"
            )

            print(rsp)
        - lang: java
          label: Java - image editing (sync)
          source: |-
            import com.alibaba.dashscope.aigc.imagegeneration.*;
            import com.alibaba.dashscope.exception.ApiException;
            import com.alibaba.dashscope.exception.NoApiKeyException;
            import com.alibaba.dashscope.exception.UploadFileException;
            import com.alibaba.dashscope.utils.Constants;
            import com.alibaba.dashscope.utils.JsonUtils;

            import java.io.IOException;
            import java.nio.file.Files;
            import java.nio.file.Paths;
            import java.util.Arrays;
            import java.util.Base64;
            import java.util.Collections;

            /**
             * wan2.7-image-pro 图像编辑 - 同步调用示例
             * 需要 SDK 版本 >= 2.22.13
             */
            public class Main {

                static {
                    Constants.baseHttpApiUrl = "https://dashscope.aliyuncs.com/api/v1";
                }

                static String apiKey = System.getenv("DASHSCOPE_API_KEY");

                public static String encodeFile(String filePath) throws IOException {
                    byte[] fileContent = Files.readAllBytes(Paths.get(filePath));
                    String base64String = Base64.getEncoder().encodeToString(fileContent);
                    String mimeType = Files.probeContentType(Paths.get(filePath));
                    return "data:" + mimeType + ";base64," + base64String;
                }

                public static void basicCall() throws ApiException, NoApiKeyException, UploadFileException {
                    // 图片输入支持三种方式：公开 URL、本地文件路径、Base64 编码
                    String image1 = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp";
                    String image2 = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp";
                    // String image1 = "file:///path/to/your/car.png";
                    // String image1 = encodeFile("/path/to/your/car.png");

                    ImageGenerationMessage message = ImageGenerationMessage.builder()
                            .role("user")
                            .content(Arrays.asList(
                                    Collections.singletonMap("text", "Spray the graffiti from image 2 onto the car in image 1"),
                                    Collections.singletonMap("image", image1),
                                    Collections.singletonMap("image", image2)
                            )).build();

                    ImageGenerationParam param = ImageGenerationParam.builder()
                            .apiKey(apiKey)
                            .model("wan2.7-image-pro")
                            .messages(Arrays.asList(message))
                            .n(1)
                            // wan2.7-image-pro 文生图支持 1K、2K 或 4K；
                            // 图像编辑和图像集生成最高支持 2K
                            .size("2K")
                            .build();

                    ImageGeneration imageGeneration = new ImageGeneration();
                    ImageGenerationResult result = null;
                    try {
                        System.out.println("---synchronous call for image editing, please wait a moment----");
                        result = imageGeneration.call(param);
                    } catch (ApiException | NoApiKeyException | UploadFileException e) {
                        throw new RuntimeException(e.getMessage());
                    }
                    System.out.println(JsonUtils.toJson(result));
                }

                public static void main(String[] args) {
                    try {
                        basicCall();
                    } catch (ApiException | NoApiKeyException | UploadFileException e) {
                        System.out.println(e.getMessage());
                    }
                }
            }
        - lang: java
          label: Java - image set generation (sync)
          source: |-
            import com.alibaba.dashscope.aigc.imagegeneration.*;
            import com.alibaba.dashscope.exception.ApiException;
            import com.alibaba.dashscope.exception.NoApiKeyException;
            import com.alibaba.dashscope.exception.UploadFileException;
            import com.alibaba.dashscope.utils.Constants;
            import com.alibaba.dashscope.utils.JsonUtils;

            import java.io.IOException;
            import java.nio.file.Files;
            import java.nio.file.Paths;
            import java.util.Arrays;
            import java.util.Base64;
            import java.util.Collections;

            /**
             * wan2.7-image-pro 图像集生成 - 同步调用示例
             * 需要 SDK 版本 >= 2.22.13
             */
            public class Main {

                static {
                    Constants.baseHttpApiUrl = "https://dashscope.aliyuncs.com/api/v1";
                }

                static String apiKey = System.getenv("DASHSCOPE_API_KEY");

                public static String encodeFile(String filePath) throws IOException {
                    byte[] fileContent = Files.readAllBytes(Paths.get(filePath));
                    String base64String = Base64.getEncoder().encodeToString(fileContent);
                    String mimeType = Files.probeContentType(Paths.get(filePath));
                    return "data:" + mimeType + ";base64," + base64String;
                }

                public static void basicCall() throws ApiException, NoApiKeyException, UploadFileException {
                    // 文生图像集（默认）
                    ImageGenerationMessage message = ImageGenerationMessage.builder()
                            .role("user")
                            .content(Collections.singletonList(
                                    Collections.singletonMap("text", "Cinematic image group, documenting the same stray orange cat, features must be consistent throughout. First image: Spring, an orange cat walks under blooming cherry trees; Second image: Summer, an orange cat rests in the shade of an old street to escape the heat; Third image: Autumn, an orange cat walks on golden fallen leaves; Fourth image: Winter, an orange cat walks on snow, leaving paw prints.")
                            )).build();

                    // 图生图像集（取消注释后使用）
                    // 图片输入支持三种方式：公开 URL、本地文件路径、Base64 编码
                    // String image1 = "https://example.com/your-image.png";
                    // String image1 = "file:///path/to/your/image.png";
                    // String image1 = encodeFile("/path/to/your/image.png");
                    // ImageGenerationMessage message = ImageGenerationMessage.builder()
                    //         .role("user")
                    //         .content(Arrays.asList(
                    //                 Collections.singletonMap("text", "Generate a sequential image set based on the input image"),
                    //                 Collections.singletonMap("image", image1)
                    //         )).build();

                    ImageGenerationParam param = ImageGenerationParam.builder()
                            .apiKey(apiKey)
                            .model("wan2.7-image-pro")
                            .messages(Collections.singletonList(message))
                            .enableSequential(true)
                            .n(4)
                            // wan2.7-image-pro 文生图支持 1K、2K 或 4K；
                            // 图像编辑和图像集生成最高支持 2K
                            .size("2K")
                            .build();

                    ImageGeneration imageGeneration = new ImageGeneration();
                    ImageGenerationResult result = null;
                    try {
                        System.out.println("----sync call, please wait a moment----");
                        result = imageGeneration.call(param);
                    } catch (ApiException | NoApiKeyException | UploadFileException e) {
                        throw new RuntimeException(e.getMessage());
                    }
                    System.out.println(JsonUtils.toJson(result));
                }

                public static void main(String[] args) {
                    try {
                        basicCall();
                    } catch (ApiException | NoApiKeyException | UploadFileException e) {
                        System.out.println(e.getMessage());
                    }
                }
            }
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      description: 千问 AI 平台 API Key。详见[获取 API Key](/api-reference/preparation/api-key)。
  schemas:
    Wan27ImageRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 模型名称。可选值：wan2.7-image-pro、wan2.7-image。
          enum:
            - wan2.7-image-pro
            - wan2.7-image
          example: wan2.7-image-pro
        input:
          type: object
          required:
            - messages
          description: 包含消息数组的输入数据。
          properties:
            messages:
              type: array
              description: 请求内容数组。目前仅支持单轮对话，即只能传入一组 role 和 content 参数，不支持多轮对话。
              minItems: 1
              maxItems: 1
              items:
                $ref: "#/components/schemas/Wan27ImageMessage"
        parameters:
          $ref: "#/components/schemas/Wan27ImageParameters"
    Wan27ImageMessage:
      type: object
      required:
        - role
        - content
      properties:
        role:
          type: string
          enum:
            - user
          description: 消息角色。必须为 `user`。
        content:
          type: array
          description: |-
            消息内容数组。必须包含一个 `text` 对象和 0 到 9 个 `image` 对象。

            使用多张图片时，在数组中放入多个 `image` 对象。图片顺序由数组位置决定。
          items:
            $ref: "#/components/schemas/Wan27ImageContentPart"
    Wan27ImageContentPart:
      type: object
      description: 图片或文本内容部分。
      properties:
        text:
          type: string
          description: 用户输入的提示词。支持中英文。长度不超过 5000 个字符（每个中文字符、字母、数字或符号均计为一个字符，超出部分自动截断）。`content` 数组中必须包含且仅包含一个 `text` 对象。
          maxLength: 5000
          example: Spray the graffiti from image 2 onto the car in image 1
        image:
          type: string
          description: |-
            输入图片，支持公开 URL（HTTP/HTTPS）或 Base64 编码字符串（`data:{mime_type};base64,{data}`）。

            **图片约束：**
            - 格式：JPEG、JPG、PNG（不支持 Alpha 通道）、BMP、WEBP。
            - 分辨率：宽和高各自在 240 到 8000 像素之间，宽高比在 [1:8, 8:1] 范围内。
            - 文件大小：最大 20 MB。
            - 数量：每次请求最多 9 张图片。
          example: https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp
    Wan27ImageParameters:
      type: object
      description: 图像处理参数。
      properties:
        size:
          type: string
          description: |-
            输出图像分辨率。支持两种指定方式，不可同时使用。

            **wan2.7-image-pro：**
            - 方式一（推荐）：`1K`、`2K`（默认）或 `4K`。
              - 适用范围：文生图（无图片输入，且非图像集生成模式）支持 1K、2K 和 4K；其他场景仅支持 1K 和 2K。
              - 总像素数：1K = 1024×1024，2K = 2048×2048，4K = 4096×4096。
              - 宽高比：有图片输入时，输出图像按最后一张输入图片的宽高比缩放到对应分辨率；无图片输入时，输出为正方形。
            - 方式二：以 `width*height` 形式指定像素数，宽高比在 [1:8, 8:1] 范围内。
              - 文生图：总像素数在 [768×768, 4096×4096] 范围内。
              - 其他场景：总像素数在 [768×768, 2048×2048] 范围内。

            **wan2.7-image：**
            - 方式一（推荐）：`1K` 或 `2K`（默认），不支持 4K。
            - 方式二：以 `width*height` 形式指定像素数。所有场景总像素数在 [768×768, 2048×2048] 范围内，宽高比在 [1:8, 8:1] 范围内。

            输出图像的实际像素值可能与指定值略有差异。
          example: 2K
        n:
          type: integer
          description: |-
            生成图像的数量。

            **注意：** `n` 的值直接影响费用。费用 = 单价 × 成功生成的图像数量。

            - 未启用图像集模式（`enable_sequential=false`）：表示生成图像的数量，范围 1–4，默认为 4。
            - 启用图像集模式（`enable_sequential=true`）：表示最多生成的图像数量，范围 1–12，默认为 12。实际数量由模型决定，不超过 `n`。
          minimum: 1
          maximum: 12
          default: 4
        enable_sequential:
          type: boolean
          description: |-
            控制图像生成模式。
            - `false`：默认值。
            - `true`：启用图像集输出模式。
          default: false
        thinking_mode:
          type: boolean
          description: 是否启用思考模式。默认为 `true`（启用）。仅在未启用图像集模式且无图片输入时生效。启用后，模型将增强推理能力以提升图像质量，但会增加生成时间。
          default: true
        bbox_list:
          type: array
          description: |-
            交互式编辑的选区。

            - 对应关系：列表长度必须与输入图片数量一致。若某张图片无需编辑，对应位置传入空列表 `[]`。
            - 坐标格式：`[x1, y1, x2, y2]`（左上角 x、左上角 y、右下角 x、右下角 y），使用原始图片的绝对像素坐标，左上角为 (0, 0)。
            - 限制：单张图片最多支持 2 个边界框。
          items:
            type: array
            description: 单张输入图片的边界框列表。空数组表示无边界框。
            items:
              type: array
              description: 单个边界框 [x1, y1, x2, y2]。
              items:
                type: integer
              minItems: 4
              maxItems: 4
            maxItems: 2
        color_palette:
          type: array
          description: 自定义色彩主题。由颜色（`hex`）和比例（`ratio`）对象组成的数组，须包含 3 到 10 种颜色（推荐设置为 8 种）。仅在未启用图像集模式（`enable_sequential=false`）时可用。
          minItems: 3
          maxItems: 10
          items:
            type: object
            required:
              - hex
              - ratio
            properties:
              hex:
                type: string
                description: 十六进制（HEX）格式的颜色值。示例：`#C2D1E6`。
              ratio:
                type: string
                description: 该颜色的占比，精确到小数点后两位（例如 `"25.00%"`）。所有 `ratio` 值之和必须为 100.00%。
          example:
            - hex: "#C2D1E6"
              ratio: 60.00%
            - hex: "#636574"
              ratio: 25.00%
            - hex: "#CBD4E4"
              ratio: 15.00%
        watermark:
          type: boolean
          description: 在图像右下角添加固定文字水印"AI Generated"。
          default: false
        seed:
          type: integer
          description: 随机数种子。有效范围：[0, 2147483647]。使用相同种子可生成相似结果。若不指定，算法将使用随机种子。注意：图像生成具有概率性，即使使用相同种子，结果也可能存在差异。
          minimum: 0
          maximum: 2147483647
    Wan27ImageResponse:
      type: object
      description: Wan2.7 图像生成响应。
      example:
        output:
          choices:
            - finish_reason: stop
              message:
                content:
                  - image: https://dashscope-result.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx
                    type: image
                role: assistant
          finished: true
        usage:
          image_count: 1
          input_tokens: 18790
          output_tokens: 2
          size: 2985*1405
          total_tokens: 18792
        request_id: a3f4befe-cacd-49c9-8298-xxxxxx
      properties:
        output:
          type: object
          properties:
            choices:
              type: array
              description: 生成结果列表。
              items:
                $ref: "#/components/schemas/Wan27ImageChoice"
            finished:
              type: boolean
              description: 生成是否已完成。
        usage:
          type: object
          description: 用量统计。
          properties:
            image_count:
              type: integer
              description: 已生成的图像数量。
            input_tokens:
              type: integer
              description: 消耗的输入 token 数量。
            output_tokens:
              type: integer
              description: 消耗的输出 token 数量。
            total_tokens:
              type: integer
              description: 消耗的总 token 数量。
            size:
              type: string
              description: 实际输出图像尺寸（宽×高）。
              example: 2985*1405
        request_id:
          type: string
          description: 唯一请求标识符。
          example: a3f4befe-cacd-49c9-8298-xxxxxx
    Wan27ImageChoice:
      type: object
      properties:
        finish_reason:
          type: string
          description: 生成完成的原因。
          example: stop
        message:
          type: object
          properties:
            role:
              type: string
              example: assistant
            content:
              type: array
              items:
                type: object
                properties:
                  image:
                    type: string
                    description: 生成图像的 URL。**URL 在 24 小时后失效，请及时下载保存。**
                    example: https://dashscope-result.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx
                  type:
                    type: string
                    example: image
    AsyncTaskSubmitResponse:
      type: object
      description: 异步任务提交成功后返回的响应。
      example:
        request_id: ccf4b2f4-bf30-9e13-9461-3a28c6a7bxxx
        output:
          task_id: 8811b4a4-00ac-4aa2-a2fd-017d3b90cxxx
          task_status: PENDING
      properties:
        request_id:
          type: string
          description: 唯一请求标识符。
          example: ccf4b2f4-bf30-9e13-9461-3a28c6a7bxxx
        output:
          type: object
          properties:
            task_id:
              type: string
              description: 任务标识符。用于轮询结果接口，24 小时内有效。
              example: 8811b4a4-00ac-4aa2-a2fd-017d3b90cxxx
            task_status:
              type: string
              description: 初始任务状态。创建完成后始终为 `PENDING`。
              example: PENDING
    Wan27TaskStatusResponse:
      type: object
      description: 任务状态查询接口的响应。
      properties:
        request_id:
          type: string
          description: 唯一请求标识符。
          example: 43d9e959-25bc-4dc7-9888-xxxxxx
        output:
          type: object
          properties:
            task_id:
              type: string
              description: 任务标识符。
              example: 858cad55-4bdc-4ba3-ae6c-xxxxxx
            task_status:
              type: string
              description: 当前任务状态：`PENDING`（排队中）、`RUNNING`（处理中）、`SUCCEEDED`（已完成）、`FAILED`（失败）、`CANCELED`（已取消）、`UNKNOWN`（任务 ID 无效或已过期）。
              enum:
                - PENDING
                - RUNNING
                - SUCCEEDED
                - FAILED
                - CANCELED
                - UNKNOWN
              example: SUCCEEDED
            submit_time:
              type: string
              description: 任务提交时间。
              example: 2026-03-31 19:57:58.840
            scheduled_time:
              type: string
              description: 任务调度时间。
              example: 2026-03-31 19:57:58.877
            end_time:
              type: string
              description: 任务完成时间。
              example: 2026-03-31 19:58:11.563
            finished:
              type: boolean
              description: 任务是否已结束。
              example: true
            choices:
              type: array
              description: 已生成的图像。仅在 `task_status` 为 `SUCCEEDED` 时存在。
              items:
                $ref: "#/components/schemas/Wan27ImageChoice"
            code:
              type: string
              description: 错误码。仅在 `task_status` 为 `FAILED` 时存在。
            message:
              type: string
              description: 错误信息。仅在 `task_status` 为 `FAILED` 时存在。
        usage:
          type: object
          description: 用量统计。仅在 `task_status` 为 `SUCCEEDED` 时存在。
          properties:
            image_count:
              type: integer
              description: 已生成的图像数量。
            input_tokens:
              type: integer
              description: 消耗的输入 token 数量。
            output_tokens:
              type: integer
              description: 消耗的输出 token 数量。
            total_tokens:
              type: integer
              description: 消耗的总 token 数量。
            size:
              type: string
              description: 实际输出图像尺寸。
              example: 2985*1405
    DashScopeErrorResponse:
      type: object
      properties:
        code:
          type: string
          description: 错误码。
          example: InvalidParameter
        message:
          type: string
          description: 错误信息。
          example: Invalid parameter value
        request_id:
          type: string
          description: 唯一请求标识符。
          example: a3f4befe-cacd-49c9-8298-xxxxxx
````





> ## Documentation Index
> Fetch the complete documentation index at: https://platform.qianwenai.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Wan 2.7 — 创建任务

> Wan 2.7 异步图像生成与编辑

<Note>
  [获取 API Key](/api-reference/preparation/api-key) 并[设置为环境变量](/api-reference/preparation/export-api-key-env)。如需使用 SDK，请先[安装 SDK](/api-reference/preparation/install-sdk)。
</Note>

图像生成任务通常需要 1 到 2 分钟。为避免请求超时，可使用异步 API 将流程拆分为两步：

1. **创建任务**（本接口），获取 `task_id`。
2. **[查询结果](/api-reference/image-generation/wan27-image-gen-edit/query-result)**，使用 `task_id` 轮询任务状态。

请求体与[同步接口](/api-reference/image-generation/wan27-image-gen-edit/synchronous)使用相同的 `messages` 格式和参数，但需要添加 `X-DashScope-Async: enable` 请求头。

## OpenAPI

````yaml post /services/aigc/image-generation/generation
openapi: 3.1.0
info:
  title: Wan2.7 图像生成与编辑 API
  description: Wan2.7 图像生成与编辑 API，支持文生图、多图编辑、边界框交互式编辑以及图像集生成。
  version: 1.0.0
servers:
  - url: https://dashscope.aliyuncs.com/api/v1
    description: 北京
security:
  - BearerAuth: []
paths:
  /services/aigc/image-generation/generation:
    post:
      operationId: createWan27ImageTask
      summary: 创建图像生成任务
      description: |-
        创建异步图像生成或编辑任务。请求体格式与同步接口相同，但需要在请求头中添加 `X-DashScope-Async: enable`。

        图像生成任务通常需要 1 到 2 分钟。建议使用异步 API 以避免请求超时。
      parameters:
        - name: X-DashScope-Async
          in: header
          required: true
          description: 异步处理配置。**必须设置为 `enable`**。
          schema:
            type: string
            enum:
              - enable
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/Wan27ImageRequest"
      responses:
        "200":
          description: 任务创建成功。
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/AsyncTaskSubmitResponse"
        "400":
          description: 请求参数无效。
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/DashScopeErrorResponse"
      x-codeSamples:
        - lang: curl
          label: cURL (text-to-image, async)
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation' \
            --header 'Content-Type: application/json' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'X-DashScope-Async: enable' \
            --data '{
              "model": "wan2.7-image-pro",
              "input": {
                "messages": [
                  {
                    "role": "user",
                    "content": [
                      {
                        "text": "A flower shop with exquisite windows, a beautiful wooden door, and flowers on display"
                      }
                    ]
                  }
                ]
              },
              "parameters": {
                "n": 1,
                "size": "2K",
                "watermark": false,
                "thinking_mode": true
              }
            }'
        - lang: curl
          label: cURL (image editing, async)
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation' \
            --header 'Content-Type: application/json' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'X-DashScope-Async: enable' \
            --data '{
              "model": "wan2.7-image-pro",
              "input": {
                "messages": [
                  {
                    "role": "user",
                    "content": [
                      {
                        "image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp"
                      },
                      {
                        "image": "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp"
                      },
                      {
                        "text": "Spray the graffiti from image 2 onto the car in image 1"
                      }
                    ]
                  }
                ]
              },
              "parameters": {
                "n": 1,
                "size": "2K",
                "watermark": false
              }
            }'
        - lang: curl
          label: cURL (interactive editing, async)
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation' \
            --header 'Content-Type: application/json' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'X-DashScope-Async: enable' \
            --data '{
              "model": "wan2.7-image-pro",
              "input": {
                "messages": [
                  {
                    "role": "user",
                    "content": [
                      {
                        "image": "https://img.alicdn.com/imgextra/i3/O1CN0157XGE51l6iL9441yX_!!6000000004770-49-tps-1104-1472.webp"
                      },
                      {
                        "image": "https://img.alicdn.com/imgextra/i3/O1CN01SfG4J41UYn9WNt4X1_!!6000000002530-49-tps-1696-960.webp"
                      },
                      {
                        "text": "Place the alarm clock from image 1 in the selected area of image 2, ensuring the scene and lighting blend naturally"
                      }
                    ]
                  }
                ]
              },
              "parameters": {
                "n": 1,
                "size": "2K",
                "watermark": false,
                "bbox_list": [[], [[989, 515, 1138, 681]]]
              }
            }'
        - lang: curl
          label: cURL (image set generation, async)
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/aigc/image-generation/generation' \
            --header 'Content-Type: application/json' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'X-DashScope-Async: enable' \
            --data '{
              "model": "wan2.7-image-pro",
              "input": {
                "messages": [
                  {
                    "role": "user",
                    "content": [
                      {
                        "text": "Cinematic image group, documenting the same stray orange cat, features must be consistent throughout. First image: Spring, an orange cat walks under blooming cherry trees; Second image: Summer, an orange cat rests in the shade of an old street to escape the heat; Third image: Autumn, an orange cat walks on golden fallen leaves; Fourth image: Winter, an orange cat walks on snow, leaving paw prints."
                      }
                    ]
                  }
                ]
              },
              "parameters": {
                "enable_sequential": true,
                "n": 4,
                "size": "2K"
              }
            }'
        - lang: python
          label: Python - image editing (async)
          source: |-
            import os
            import base64
            import mimetypes
            import dashscope
            from dashscope.aigc.image_generation import ImageGeneration
            from dashscope.api_entities.dashscope_response import Message

            # 需要 SDK 版本 >= 1.25.15
            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

            api_key = os.getenv("DASHSCOPE_API_KEY")

            def encode_file(file_path):
              mime_type, _ = mimetypes.guess_type(file_path)
              if not mime_type or not mime_type.startswith("image/"):
                raise ValueError("Unsupported or unrecognized image format")
              with open(file_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
              return f"data:{mime_type};base64,{encoded_string}"

            # 图片输入支持三种方式：公开 URL、本地文件路径、Base64 编码
            image_1 = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp"
            image_2 = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp"
            # image_1 = "file:///path/to/your/car.png"
            # image_1 = encode_file("/path/to/your/car.png")

            message = Message(
              role="user",
              content=[
                {"text": "Spray the graffiti from image 2 onto the car in image 1"},
                {"image": image_1},
                {"image": image_2}
              ]
            )

            print("---async call for image editing, creating task----")
            response = ImageGeneration.async_call(
              model='wan2.7-image-pro',
              api_key=api_key,
              messages=[message],
              n=1,
              # wan2.7-image-pro 文生图支持 1K、2K 或 4K；
              # 图像编辑和图像集生成最高支持 2K
              size="2K",
              watermark=False
            )

            print("Task created:", response)

            # 等待任务完成
            result = ImageGeneration.wait(task=response, api_key=api_key)
            print(result)
        - lang: python
          label: Python - image set generation (async)
          source: |-
            import os
            import base64
            import mimetypes
            import dashscope
            from dashscope.aigc.image_generation import ImageGeneration
            from dashscope.api_entities.dashscope_response import Message

            # 需要 SDK 版本 >= 1.25.15
            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

            api_key = os.getenv("DASHSCOPE_API_KEY")

            def encode_file(file_path):
              mime_type, _ = mimetypes.guess_type(file_path)
              if not mime_type or not mime_type.startswith("image/"):
                raise ValueError("Unsupported or unrecognized image format")
              with open(file_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
              return f"data:{mime_type};base64,{encoded_string}"

            # 文生图像集（默认）
            message = Message(
              role="user",
              content=[
                {"text": "Cinematic image group, documenting the same stray orange cat, features must be consistent throughout. First image: Spring, an orange cat walks under blooming cherry trees; Second image: Summer, an orange cat rests in the shade of an old street to escape the heat; Third image: Autumn, an orange cat walks on golden fallen leaves; Fourth image: Winter, an orange cat walks on snow, leaving paw prints."}
              ]
            )

            # 图生图像集（取消注释后使用）
            # 图片输入支持三种方式：公开 URL、本地文件路径、Base64 编码
            # image_1 = "https://example.com/your-image.png"
            # image_1 = "file:///path/to/your/image.png"
            # image_1 = encode_file("/path/to/your/image.png")
            # message = Message(
            #   role="user",
            #   content=[
            #     {"text": "Generate a sequential image set based on the input image"},
            #     {"image": image_1}
            #   ]
            # )

            print("---async call for image set generation, creating task----")
            response = ImageGeneration.async_call(
              model='wan2.7-image-pro',
              api_key=api_key,
              messages=[message],
              enable_sequential=True,
              n=4,
              # wan2.7-image-pro 文生图支持 1K、2K 或 4K；
              # 图像编辑和图像集生成最高支持 2K
              size="2K"
            )

            print("Task created:", response)

            # 等待任务完成
            result = ImageGeneration.wait(task=response, api_key=api_key)
            print(result)
        - lang: java
          label: Java - image editing (async)
          source: |-
            import com.alibaba.dashscope.aigc.imagegeneration.*;
            import com.alibaba.dashscope.exception.ApiException;
            import com.alibaba.dashscope.exception.NoApiKeyException;
            import com.alibaba.dashscope.exception.UploadFileException;
            import com.alibaba.dashscope.utils.Constants;
            import com.alibaba.dashscope.utils.JsonUtils;

            import java.io.IOException;
            import java.nio.file.Files;
            import java.nio.file.Paths;
            import java.util.Arrays;
            import java.util.Base64;
            import java.util.Collections;

            /**
             * wan2.7-image-pro 图像编辑 - 异步调用示例
             * 需要 SDK 版本 >= 2.22.13
             */
            public class Main {

                static {
                    Constants.baseHttpApiUrl = "https://dashscope.aliyuncs.com/api/v1";
                }

                static String apiKey = System.getenv("DASHSCOPE_API_KEY");

                public static String encodeFile(String filePath) throws IOException {
                    byte[] fileContent = Files.readAllBytes(Paths.get(filePath));
                    String base64String = Base64.getEncoder().encodeToString(fileContent);
                    String mimeType = Files.probeContentType(Paths.get(filePath));
                    return "data:" + mimeType + ";base64," + base64String;
                }

                public static void asyncCall() throws ApiException, NoApiKeyException, UploadFileException {
                    // 图片输入支持三种方式：公开 URL、本地文件路径、Base64 编码
                    String image1 = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp";
                    String image2 = "https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/xsunlm/paint.webp";
                    // String image1 = "file:///path/to/your/car.png";
                    // String image1 = encodeFile("/path/to/your/car.png");

                    ImageGenerationMessage message = ImageGenerationMessage.builder()
                            .role("user")
                            .content(Arrays.asList(
                                    Collections.singletonMap("text", "Spray the graffiti from image 2 onto the car in image 1"),
                                    Collections.singletonMap("image", image1),
                                    Collections.singletonMap("image", image2)
                            )).build();

                    ImageGenerationParam param = ImageGenerationParam.builder()
                            .apiKey(apiKey)
                            .model("wan2.7-image-pro")
                            .n(1)
                            // wan2.7-image-pro 文生图支持 1K、2K 或 4K；
                            // 图像编辑和图像集生成最高支持 2K
                            .size("2K")
                            .messages(Arrays.asList(message))
                            .build();

                    ImageGeneration imageGeneration = new ImageGeneration();
                    ImageGenerationResult result = null;
                    try {
                        System.out.println("---asynchronous call for image editing, creating task----");
                        result = imageGeneration.asyncCall(param);
                    } catch (ApiException | NoApiKeyException | UploadFileException e) {
                        throw new RuntimeException(e.getMessage());
                    }
                    System.out.println("Task creation result:");
                    System.out.println(JsonUtils.toJson(result));

                    String taskId = result.getOutput().getTaskId();
                    waitTask(taskId);
                }

                public static void waitTask(String taskId) throws ApiException, NoApiKeyException {
                    ImageGeneration imageGeneration = new ImageGeneration();
                    System.out.println("\n---waiting for task completion----");
                    ImageGenerationResult result = imageGeneration.wait(taskId, apiKey);
                    System.out.println("Task completion result:");
                    System.out.println(JsonUtils.toJson(result));
                }

                public static void main(String[] args) {
                    try {
                        asyncCall();
                    } catch (ApiException | NoApiKeyException | UploadFileException e) {
                        System.out.println(e.getMessage());
                    }
                }
            }
        - lang: java
          label: Java - image set generation (async)
          source: |-
            import com.alibaba.dashscope.aigc.imagegeneration.*;
            import com.alibaba.dashscope.exception.ApiException;
            import com.alibaba.dashscope.exception.NoApiKeyException;
            import com.alibaba.dashscope.exception.UploadFileException;
            import com.alibaba.dashscope.utils.Constants;
            import com.alibaba.dashscope.utils.JsonUtils;

            import java.io.IOException;
            import java.nio.file.Files;
            import java.nio.file.Paths;
            import java.util.Arrays;
            import java.util.Base64;
            import java.util.Collections;

            /**
             * wan2.7-image-pro 图像集生成 - 异步调用示例
             * 需要 SDK 版本 >= 2.22.13
             */
            public class Main {

                static {
                    Constants.baseHttpApiUrl = "https://dashscope.aliyuncs.com/api/v1";
                }

                static String apiKey = System.getenv("DASHSCOPE_API_KEY");

                public static String encodeFile(String filePath) throws IOException {
                    byte[] fileContent = Files.readAllBytes(Paths.get(filePath));
                    String base64String = Base64.getEncoder().encodeToString(fileContent);
                    String mimeType = Files.probeContentType(Paths.get(filePath));
                    return "data:" + mimeType + ";base64," + base64String;
                }

                public static ImageGenerationResult waitTask(String taskId)
                        throws ApiException, NoApiKeyException {
                    ImageGeneration imageGeneration = new ImageGeneration();
                    return imageGeneration.wait(taskId, apiKey);
                }

                public static void asyncCall() throws ApiException, NoApiKeyException, UploadFileException {
                    // 文生图像集（默认）
                    ImageGenerationMessage message = ImageGenerationMessage.builder()
                            .role("user")
                            .content(Collections.singletonList(
                                    Collections.singletonMap("text", "Cinematic image group, documenting the same stray orange cat, features must be consistent throughout. First image: Spring, an orange cat walks under blooming cherry trees; Second image: Summer, an orange cat rests in the shade of an old street to escape the heat; Third image: Autumn, an orange cat walks on golden fallen leaves; Fourth image: Winter, an orange cat walks on snow, leaving paw prints.")
                            )).build();

                    // 图生图像集（取消注释后使用）
                    // 图片输入支持三种方式：公开 URL、本地文件路径、Base64 编码
                    // String image1 = "https://example.com/your-image.png";
                    // String image1 = "file:///path/to/your/image.png";
                    // String image1 = encodeFile("/path/to/your/image.png");
                    // ImageGenerationMessage message = ImageGenerationMessage.builder()
                    //         .role("user")
                    //         .content(Arrays.asList(
                    //                 Collections.singletonMap("text", "Generate a sequential image set based on the input image"),
                    //                 Collections.singletonMap("image", image1)
                    //         )).build();

                    ImageGenerationParam param = ImageGenerationParam.builder()
                            .apiKey(apiKey)
                            .model("wan2.7-image-pro")
                            .messages(Collections.singletonList(message))
                            .enableSequential(true)
                            .n(4)
                            // wan2.7-image-pro 文生图支持 1K、2K 或 4K；
                            // 图像编辑和图像集生成最高支持 2K
                            .size("2K")
                            .build();

                    ImageGeneration imageGeneration = new ImageGeneration();
                    ImageGenerationResult taskResult = null;
                    try {
                        System.out.println("----async call, creating task----");
                        taskResult = imageGeneration.asyncCall(param);
                    } catch (ApiException | NoApiKeyException | UploadFileException e) {
                        throw new RuntimeException(e.getMessage());
                    }
                    System.out.println("Task created: " + JsonUtils.toJson(taskResult));

                    String taskId = taskResult.getOutput().getTaskId();
                    ImageGenerationResult result = waitTask(taskId);
                    System.out.println(JsonUtils.toJson(result));
                }

                public static void main(String[] args) {
                    try {
                        asyncCall();
                    } catch (ApiException | NoApiKeyException | UploadFileException e) {
                        System.out.println(e.getMessage());
                    }
                }
            }
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      description: 千问 AI 平台 API Key。详见[获取 API Key](/api-reference/preparation/api-key)。
  schemas:
    Wan27ImageRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 模型名称。可选值：wan2.7-image-pro、wan2.7-image。
          enum:
            - wan2.7-image-pro
            - wan2.7-image
          example: wan2.7-image-pro
        input:
          type: object
          required:
            - messages
          description: 包含消息数组的输入数据。
          properties:
            messages:
              type: array
              description: 请求内容数组。目前仅支持单轮对话，即只能传入一组 role 和 content 参数，不支持多轮对话。
              minItems: 1
              maxItems: 1
              items:
                $ref: "#/components/schemas/Wan27ImageMessage"
        parameters:
          $ref: "#/components/schemas/Wan27ImageParameters"
    Wan27ImageMessage:
      type: object
      required:
        - role
        - content
      properties:
        role:
          type: string
          enum:
            - user
          description: 消息角色。必须为 `user`。
        content:
          type: array
          description: |-
            消息内容数组。必须包含一个 `text` 对象和 0 到 9 个 `image` 对象。

            使用多张图片时，在数组中放入多个 `image` 对象。图片顺序由数组位置决定。
          items:
            $ref: "#/components/schemas/Wan27ImageContentPart"
    Wan27ImageContentPart:
      type: object
      description: 图片或文本内容部分。
      properties:
        text:
          type: string
          description: 用户输入的提示词。支持中英文。长度不超过 5000 个字符（每个中文字符、字母、数字或符号均计为一个字符，超出部分自动截断）。`content` 数组中必须包含且仅包含一个 `text` 对象。
          maxLength: 5000
          example: Spray the graffiti from image 2 onto the car in image 1
        image:
          type: string
          description: |-
            输入图片，支持公开 URL（HTTP/HTTPS）或 Base64 编码字符串（`data:{mime_type};base64,{data}`）。

            **图片约束：**
            - 格式：JPEG、JPG、PNG（不支持 Alpha 通道）、BMP、WEBP。
            - 分辨率：宽和高各自在 240 到 8000 像素之间，宽高比在 [1:8, 8:1] 范围内。
            - 文件大小：最大 20 MB。
            - 数量：每次请求最多 9 张图片。
          example: https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp
    Wan27ImageParameters:
      type: object
      description: 图像处理参数。
      properties:
        size:
          type: string
          description: |-
            输出图像分辨率。支持两种指定方式，不可同时使用。

            **wan2.7-image-pro：**
            - 方式一（推荐）：`1K`、`2K`（默认）或 `4K`。
              - 适用范围：文生图（无图片输入，且非图像集生成模式）支持 1K、2K 和 4K；其他场景仅支持 1K 和 2K。
              - 总像素数：1K = 1024×1024，2K = 2048×2048，4K = 4096×4096。
              - 宽高比：有图片输入时，输出图像按最后一张输入图片的宽高比缩放到对应分辨率；无图片输入时，输出为正方形。
            - 方式二：以 `width*height` 形式指定像素数，宽高比在 [1:8, 8:1] 范围内。
              - 文生图：总像素数在 [768×768, 4096×4096] 范围内。
              - 其他场景：总像素数在 [768×768, 2048×2048] 范围内。

            **wan2.7-image：**
            - 方式一（推荐）：`1K` 或 `2K`（默认），不支持 4K。
            - 方式二：以 `width*height` 形式指定像素数。所有场景总像素数在 [768×768, 2048×2048] 范围内，宽高比在 [1:8, 8:1] 范围内。

            输出图像的实际像素值可能与指定值略有差异。
          example: 2K
        n:
          type: integer
          description: |-
            生成图像的数量。

            **注意：** `n` 的值直接影响费用。费用 = 单价 × 成功生成的图像数量。

            - 未启用图像集模式（`enable_sequential=false`）：表示生成图像的数量，范围 1–4，默认为 4。
            - 启用图像集模式（`enable_sequential=true`）：表示最多生成的图像数量，范围 1–12，默认为 12。实际数量由模型决定，不超过 `n`。
          minimum: 1
          maximum: 12
          default: 4
        enable_sequential:
          type: boolean
          description: |-
            控制图像生成模式。
            - `false`：默认值。
            - `true`：启用图像集输出模式。
          default: false
        thinking_mode:
          type: boolean
          description: 是否启用思考模式。默认为 `true`（启用）。仅在未启用图像集模式且无图片输入时生效。启用后，模型将增强推理能力以提升图像质量，但会增加生成时间。
          default: true
        bbox_list:
          type: array
          description: |-
            交互式编辑的选区。

            - 对应关系：列表长度必须与输入图片数量一致。若某张图片无需编辑，对应位置传入空列表 `[]`。
            - 坐标格式：`[x1, y1, x2, y2]`（左上角 x、左上角 y、右下角 x、右下角 y），使用原始图片的绝对像素坐标，左上角为 (0, 0)。
            - 限制：单张图片最多支持 2 个边界框。
          items:
            type: array
            description: 单张输入图片的边界框列表。空数组表示无边界框。
            items:
              type: array
              description: 单个边界框 [x1, y1, x2, y2]。
              items:
                type: integer
              minItems: 4
              maxItems: 4
            maxItems: 2
        color_palette:
          type: array
          description: 自定义色彩主题。由颜色（`hex`）和比例（`ratio`）对象组成的数组，须包含 3 到 10 种颜色（推荐设置为 8 种）。仅在未启用图像集模式（`enable_sequential=false`）时可用。
          minItems: 3
          maxItems: 10
          items:
            type: object
            required:
              - hex
              - ratio
            properties:
              hex:
                type: string
                description: 十六进制（HEX）格式的颜色值。示例：`#C2D1E6`。
              ratio:
                type: string
                description: 该颜色的占比，精确到小数点后两位（例如 `"25.00%"`）。所有 `ratio` 值之和必须为 100.00%。
          example:
            - hex: "#C2D1E6"
              ratio: 60.00%
            - hex: "#636574"
              ratio: 25.00%
            - hex: "#CBD4E4"
              ratio: 15.00%
        watermark:
          type: boolean
          description: 在图像右下角添加固定文字水印"AI Generated"。
          default: false
        seed:
          type: integer
          description: 随机数种子。有效范围：[0, 2147483647]。使用相同种子可生成相似结果。若不指定，算法将使用随机种子。注意：图像生成具有概率性，即使使用相同种子，结果也可能存在差异。
          minimum: 0
          maximum: 2147483647
    Wan27ImageResponse:
      type: object
      description: Wan2.7 图像生成响应。
      example:
        output:
          choices:
            - finish_reason: stop
              message:
                content:
                  - image: https://dashscope-result.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx
                    type: image
                role: assistant
          finished: true
        usage:
          image_count: 1
          input_tokens: 18790
          output_tokens: 2
          size: 2985*1405
          total_tokens: 18792
        request_id: a3f4befe-cacd-49c9-8298-xxxxxx
      properties:
        output:
          type: object
          properties:
            choices:
              type: array
              description: 生成结果列表。
              items:
                $ref: "#/components/schemas/Wan27ImageChoice"
            finished:
              type: boolean
              description: 生成是否已完成。
        usage:
          type: object
          description: 用量统计。
          properties:
            image_count:
              type: integer
              description: 已生成的图像数量。
            input_tokens:
              type: integer
              description: 消耗的输入 token 数量。
            output_tokens:
              type: integer
              description: 消耗的输出 token 数量。
            total_tokens:
              type: integer
              description: 消耗的总 token 数量。
            size:
              type: string
              description: 实际输出图像尺寸（宽×高）。
              example: 2985*1405
        request_id:
          type: string
          description: 唯一请求标识符。
          example: a3f4befe-cacd-49c9-8298-xxxxxx
    Wan27ImageChoice:
      type: object
      properties:
        finish_reason:
          type: string
          description: 生成完成的原因。
          example: stop
        message:
          type: object
          properties:
            role:
              type: string
              example: assistant
            content:
              type: array
              items:
                type: object
                properties:
                  image:
                    type: string
                    description: 生成图像的 URL。**URL 在 24 小时后失效，请及时下载保存。**
                    example: https://dashscope-result.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx
                  type:
                    type: string
                    example: image
    AsyncTaskSubmitResponse:
      type: object
      description: 异步任务提交成功后返回的响应。
      example:
        request_id: ccf4b2f4-bf30-9e13-9461-3a28c6a7bxxx
        output:
          task_id: 8811b4a4-00ac-4aa2-a2fd-017d3b90cxxx
          task_status: PENDING
      properties:
        request_id:
          type: string
          description: 唯一请求标识符。
          example: ccf4b2f4-bf30-9e13-9461-3a28c6a7bxxx
        output:
          type: object
          properties:
            task_id:
              type: string
              description: 任务标识符。用于轮询结果接口，24 小时内有效。
              example: 8811b4a4-00ac-4aa2-a2fd-017d3b90cxxx
            task_status:
              type: string
              description: 初始任务状态。创建完成后始终为 `PENDING`。
              example: PENDING
    Wan27TaskStatusResponse:
      type: object
      description: 任务状态查询接口的响应。
      properties:
        request_id:
          type: string
          description: 唯一请求标识符。
          example: 43d9e959-25bc-4dc7-9888-xxxxxx
        output:
          type: object
          properties:
            task_id:
              type: string
              description: 任务标识符。
              example: 858cad55-4bdc-4ba3-ae6c-xxxxxx
            task_status:
              type: string
              description: 当前任务状态：`PENDING`（排队中）、`RUNNING`（处理中）、`SUCCEEDED`（已完成）、`FAILED`（失败）、`CANCELED`（已取消）、`UNKNOWN`（任务 ID 无效或已过期）。
              enum:
                - PENDING
                - RUNNING
                - SUCCEEDED
                - FAILED
                - CANCELED
                - UNKNOWN
              example: SUCCEEDED
            submit_time:
              type: string
              description: 任务提交时间。
              example: 2026-03-31 19:57:58.840
            scheduled_time:
              type: string
              description: 任务调度时间。
              example: 2026-03-31 19:57:58.877
            end_time:
              type: string
              description: 任务完成时间。
              example: 2026-03-31 19:58:11.563
            finished:
              type: boolean
              description: 任务是否已结束。
              example: true
            choices:
              type: array
              description: 已生成的图像。仅在 `task_status` 为 `SUCCEEDED` 时存在。
              items:
                $ref: "#/components/schemas/Wan27ImageChoice"
            code:
              type: string
              description: 错误码。仅在 `task_status` 为 `FAILED` 时存在。
            message:
              type: string
              description: 错误信息。仅在 `task_status` 为 `FAILED` 时存在。
        usage:
          type: object
          description: 用量统计。仅在 `task_status` 为 `SUCCEEDED` 时存在。
          properties:
            image_count:
              type: integer
              description: 已生成的图像数量。
            input_tokens:
              type: integer
              description: 消耗的输入 token 数量。
            output_tokens:
              type: integer
              description: 消耗的输出 token 数量。
            total_tokens:
              type: integer
              description: 消耗的总 token 数量。
            size:
              type: string
              description: 实际输出图像尺寸。
              example: 2985*1405
    DashScopeErrorResponse:
      type: object
      properties:
        code:
          type: string
          description: 错误码。
          example: InvalidParameter
        message:
          type: string
          description: 错误信息。
          example: Invalid parameter value
        request_id:
          type: string
          description: 唯一请求标识符。
          example: a3f4befe-cacd-49c9-8298-xxxxxx
````





> ## Documentation Index
> Fetch the complete documentation index at: https://platform.qianwenai.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Wan 2.7 — 查询结果

> 查询 Wan 2.7 图像任务状态

查询任务状态和结果。

## 轮询策略

使用返回的 `task_id` 轮询此接口，建议每 **5-10 秒**轮询一次。

## 注意事项

- **URL 有效期**：图片 URL 在 **24 小时**后过期，请及时下载。
- **任务状态流转**：`PENDING` → `RUNNING` → `SUCCEEDED` 或 `FAILED`。
- **其他状态**：`CANCELED`（任务已取消）、`UNKNOWN`（任务 ID 无效或已过期）。
- **`task_id` 有效期**：`task_id` 有效期为 24 小时，过期后无法查询状态和结果。
- **避免重复提交**：请通过轮询获取结果，不要重复提交请求。

## OpenAPI

````yaml get /tasks/{task_id}
openapi: 3.1.0
info:
  title: Wan2.7 图像生成与编辑 API
  description: Wan2.7 图像生成与编辑 API，支持文生图、多图编辑、边界框交互式编辑以及图像集生成。
  version: 1.0.0
servers:
  - url: https://dashscope.aliyuncs.com/api/v1
    description: 北京
security:
  - BearerAuth: []
paths:
  /tasks/{task_id}:
    get:
      operationId: getWan27ImageTaskResult
      summary: 查询任务结果
      description: 查询异步图像任务的状态和结果。
      parameters:
        - name: task_id
          in: path
          required: true
          description: 异步任务创建接口返回的任务标识符。
          schema:
            type: string
      responses:
        "200":
          description: 成功获取任务状态。
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Wan27TaskStatusResponse"
              examples:
                SUCCEEDED:
                  summary: 任务成功
                  value:
                    request_id: 43d9e959-25bc-4dc7-9888-xxxxxx
                    output:
                      task_id: 858cad55-4bdc-4ba3-ae6c-xxxxxx
                      task_status: SUCCEEDED
                      submit_time: 2026-03-31 19:57:58.840
                      scheduled_time: 2026-03-31 19:57:58.877
                      end_time: 2026-03-31 19:58:11.563
                      finished: true
                      choices:
                        - finish_reason: stop
                          message:
                            role: assistant
                            content:
                              - image: https://dashscope-result.oss-cn-shanghai.aliyuncs.com/1xxx.png?Expires=xxx
                                type: image
                    usage:
                      size: 2985*1405
                      total_tokens: 18792
                      image_count: 1
                      output_tokens: 2
                      input_tokens: 18790
                FAILED:
                  summary: 任务失败
                  value:
                    request_id: a4d78a5f-655f-9639-8437-xxxxxx
                    output:
                      task_id: 858cad55-4bdc-4ba3-ae6c-xxxxxx
                      task_status: FAILED
                      code: InvalidParameter
                      message: Invalid parameter value
                RUNNING:
                  summary: 任务执行中
                  value:
                    request_id: c1209113-8437-424f-a386-xxxxxx
                    output:
                      task_id: 858cad55-4bdc-4ba3-ae6c-xxxxxx
                      task_status: RUNNING
        "400":
          description: 请求参数无效。
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/DashScopeErrorResponse"
      x-codeSamples:
        - lang: curl
          label: cURL - Query task result
          source: |-
            # 将 {task_id} 替换为上一次 API 调用返回的 task_id 值。
            # task_id 在 24 小时内有效。
            curl -X GET https://dashscope.aliyuncs.com/api/v1/tasks/{task_id} \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY"
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      description: 千问 AI 平台 API Key。详见[获取 API Key](/api-reference/preparation/api-key)。
  schemas:
    Wan27ImageRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 模型名称。可选值：wan2.7-image-pro、wan2.7-image。
          enum:
            - wan2.7-image-pro
            - wan2.7-image
          example: wan2.7-image-pro
        input:
          type: object
          required:
            - messages
          description: 包含消息数组的输入数据。
          properties:
            messages:
              type: array
              description: 请求内容数组。目前仅支持单轮对话，即只能传入一组 role 和 content 参数，不支持多轮对话。
              minItems: 1
              maxItems: 1
              items:
                $ref: "#/components/schemas/Wan27ImageMessage"
        parameters:
          $ref: "#/components/schemas/Wan27ImageParameters"
    Wan27ImageMessage:
      type: object
      required:
        - role
        - content
      properties:
        role:
          type: string
          enum:
            - user
          description: 消息角色。必须为 `user`。
        content:
          type: array
          description: |-
            消息内容数组。必须包含一个 `text` 对象和 0 到 9 个 `image` 对象。

            使用多张图片时，在数组中放入多个 `image` 对象。图片顺序由数组位置决定。
          items:
            $ref: "#/components/schemas/Wan27ImageContentPart"
    Wan27ImageContentPart:
      type: object
      description: 图片或文本内容部分。
      properties:
        text:
          type: string
          description: 用户输入的提示词。支持中英文。长度不超过 5000 个字符（每个中文字符、字母、数字或符号均计为一个字符，超出部分自动截断）。`content` 数组中必须包含且仅包含一个 `text` 对象。
          maxLength: 5000
          example: Spray the graffiti from image 2 onto the car in image 1
        image:
          type: string
          description: |-
            输入图片，支持公开 URL（HTTP/HTTPS）或 Base64 编码字符串（`data:{mime_type};base64,{data}`）。

            **图片约束：**
            - 格式：JPEG、JPG、PNG（不支持 Alpha 通道）、BMP、WEBP。
            - 分辨率：宽和高各自在 240 到 8000 像素之间，宽高比在 [1:8, 8:1] 范围内。
            - 文件大小：最大 20 MB。
            - 数量：每次请求最多 9 张图片。
          example: https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20251229/pjeqdf/car.webp
    Wan27ImageParameters:
      type: object
      description: 图像处理参数。
      properties:
        size:
          type: string
          description: |-
            输出图像分辨率。支持两种指定方式，不可同时使用。

            **wan2.7-image-pro：**
            - 方式一（推荐）：`1K`、`2K`（默认）或 `4K`。
              - 适用范围：文生图（无图片输入，且非图像集生成模式）支持 1K、2K 和 4K；其他场景仅支持 1K 和 2K。
              - 总像素数：1K = 1024×1024，2K = 2048×2048，4K = 4096×4096。
              - 宽高比：有图片输入时，输出图像按最后一张输入图片的宽高比缩放到对应分辨率；无图片输入时，输出为正方形。
            - 方式二：以 `width*height` 形式指定像素数，宽高比在 [1:8, 8:1] 范围内。
              - 文生图：总像素数在 [768×768, 4096×4096] 范围内。
              - 其他场景：总像素数在 [768×768, 2048×2048] 范围内。

            **wan2.7-image：**
            - 方式一（推荐）：`1K` 或 `2K`（默认），不支持 4K。
            - 方式二：以 `width*height` 形式指定像素数。所有场景总像素数在 [768×768, 2048×2048] 范围内，宽高比在 [1:8, 8:1] 范围内。

            输出图像的实际像素值可能与指定值略有差异。
          example: 2K
        n:
          type: integer
          description: |-
            生成图像的数量。

            **注意：** `n` 的值直接影响费用。费用 = 单价 × 成功生成的图像数量。

            - 未启用图像集模式（`enable_sequential=false`）：表示生成图像的数量，范围 1–4，默认为 4。
            - 启用图像集模式（`enable_sequential=true`）：表示最多生成的图像数量，范围 1–12，默认为 12。实际数量由模型决定，不超过 `n`。
          minimum: 1
          maximum: 12
          default: 4
        enable_sequential:
          type: boolean
          description: |-
            控制图像生成模式。
            - `false`：默认值。
            - `true`：启用图像集输出模式。
          default: false
        thinking_mode:
          type: boolean
          description: 是否启用思考模式。默认为 `true`（启用）。仅在未启用图像集模式且无图片输入时生效。启用后，模型将增强推理能力以提升图像质量，但会增加生成时间。
          default: true
        bbox_list:
          type: array
          description: |-
            交互式编辑的选区。

            - 对应关系：列表长度必须与输入图片数量一致。若某张图片无需编辑，对应位置传入空列表 `[]`。
            - 坐标格式：`[x1, y1, x2, y2]`（左上角 x、左上角 y、右下角 x、右下角 y），使用原始图片的绝对像素坐标，左上角为 (0, 0)。
            - 限制：单张图片最多支持 2 个边界框。
          items:
            type: array
            description: 单张输入图片的边界框列表。空数组表示无边界框。
            items:
              type: array
              description: 单个边界框 [x1, y1, x2, y2]。
              items:
                type: integer
              minItems: 4
              maxItems: 4
            maxItems: 2
        color_palette:
          type: array
          description: 自定义色彩主题。由颜色（`hex`）和比例（`ratio`）对象组成的数组，须包含 3 到 10 种颜色（推荐设置为 8 种）。仅在未启用图像集模式（`enable_sequential=false`）时可用。
          minItems: 3
          maxItems: 10
          items:
            type: object
            required:
              - hex
              - ratio
            properties:
              hex:
                type: string
                description: 十六进制（HEX）格式的颜色值。示例：`#C2D1E6`。
              ratio:
                type: string
                description: 该颜色的占比，精确到小数点后两位（例如 `"25.00%"`）。所有 `ratio` 值之和必须为 100.00%。
          example:
            - hex: "#C2D1E6"
              ratio: 60.00%
            - hex: "#636574"
              ratio: 25.00%
            - hex: "#CBD4E4"
              ratio: 15.00%
        watermark:
          type: boolean
          description: 在图像右下角添加固定文字水印"AI Generated"。
          default: false
        seed:
          type: integer
          description: 随机数种子。有效范围：[0, 2147483647]。使用相同种子可生成相似结果。若不指定，算法将使用随机种子。注意：图像生成具有概率性，即使使用相同种子，结果也可能存在差异。
          minimum: 0
          maximum: 2147483647
    Wan27ImageResponse:
      type: object
      description: Wan2.7 图像生成响应。
      example:
        output:
          choices:
            - finish_reason: stop
              message:
                content:
                  - image: https://dashscope-result.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx
                    type: image
                role: assistant
          finished: true
        usage:
          image_count: 1
          input_tokens: 18790
          output_tokens: 2
          size: 2985*1405
          total_tokens: 18792
        request_id: a3f4befe-cacd-49c9-8298-xxxxxx
      properties:
        output:
          type: object
          properties:
            choices:
              type: array
              description: 生成结果列表。
              items:
                $ref: "#/components/schemas/Wan27ImageChoice"
            finished:
              type: boolean
              description: 生成是否已完成。
        usage:
          type: object
          description: 用量统计。
          properties:
            image_count:
              type: integer
              description: 已生成的图像数量。
            input_tokens:
              type: integer
              description: 消耗的输入 token 数量。
            output_tokens:
              type: integer
              description: 消耗的输出 token 数量。
            total_tokens:
              type: integer
              description: 消耗的总 token 数量。
            size:
              type: string
              description: 实际输出图像尺寸（宽×高）。
              example: 2985*1405
        request_id:
          type: string
          description: 唯一请求标识符。
          example: a3f4befe-cacd-49c9-8298-xxxxxx
    Wan27ImageChoice:
      type: object
      properties:
        finish_reason:
          type: string
          description: 生成完成的原因。
          example: stop
        message:
          type: object
          properties:
            role:
              type: string
              example: assistant
            content:
              type: array
              items:
                type: object
                properties:
                  image:
                    type: string
                    description: 生成图像的 URL。**URL 在 24 小时后失效，请及时下载保存。**
                    example: https://dashscope-result.oss-cn-shanghai.aliyuncs.com/xxx.png?Expires=xxx
                  type:
                    type: string
                    example: image
    AsyncTaskSubmitResponse:
      type: object
      description: 异步任务提交成功后返回的响应。
      example:
        request_id: ccf4b2f4-bf30-9e13-9461-3a28c6a7bxxx
        output:
          task_id: 8811b4a4-00ac-4aa2-a2fd-017d3b90cxxx
          task_status: PENDING
      properties:
        request_id:
          type: string
          description: 唯一请求标识符。
          example: ccf4b2f4-bf30-9e13-9461-3a28c6a7bxxx
        output:
          type: object
          properties:
            task_id:
              type: string
              description: 任务标识符。用于轮询结果接口，24 小时内有效。
              example: 8811b4a4-00ac-4aa2-a2fd-017d3b90cxxx
            task_status:
              type: string
              description: 初始任务状态。创建完成后始终为 `PENDING`。
              example: PENDING
    Wan27TaskStatusResponse:
      type: object
      description: 任务状态查询接口的响应。
      properties:
        request_id:
          type: string
          description: 唯一请求标识符。
          example: 43d9e959-25bc-4dc7-9888-xxxxxx
        output:
          type: object
          properties:
            task_id:
              type: string
              description: 任务标识符。
              example: 858cad55-4bdc-4ba3-ae6c-xxxxxx
            task_status:
              type: string
              description: 当前任务状态：`PENDING`（排队中）、`RUNNING`（处理中）、`SUCCEEDED`（已完成）、`FAILED`（失败）、`CANCELED`（已取消）、`UNKNOWN`（任务 ID 无效或已过期）。
              enum:
                - PENDING
                - RUNNING
                - SUCCEEDED
                - FAILED
                - CANCELED
                - UNKNOWN
              example: SUCCEEDED
            submit_time:
              type: string
              description: 任务提交时间。
              example: 2026-03-31 19:57:58.840
            scheduled_time:
              type: string
              description: 任务调度时间。
              example: 2026-03-31 19:57:58.877
            end_time:
              type: string
              description: 任务完成时间。
              example: 2026-03-31 19:58:11.563
            finished:
              type: boolean
              description: 任务是否已结束。
              example: true
            choices:
              type: array
              description: 已生成的图像。仅在 `task_status` 为 `SUCCEEDED` 时存在。
              items:
                $ref: "#/components/schemas/Wan27ImageChoice"
            code:
              type: string
              description: 错误码。仅在 `task_status` 为 `FAILED` 时存在。
            message:
              type: string
              description: 错误信息。仅在 `task_status` 为 `FAILED` 时存在。
        usage:
          type: object
          description: 用量统计。仅在 `task_status` 为 `SUCCEEDED` 时存在。
          properties:
            image_count:
              type: integer
              description: 已生成的图像数量。
            input_tokens:
              type: integer
              description: 消耗的输入 token 数量。
            output_tokens:
              type: integer
              description: 消耗的输出 token 数量。
            total_tokens:
              type: integer
              description: 消耗的总 token 数量。
            size:
              type: string
              description: 实际输出图像尺寸。
              example: 2985*1405
    DashScopeErrorResponse:
      type: object
      properties:
        code:
          type: string
          description: 错误码。
          example: InvalidParameter
        message:
          type: string
          description: 错误信息。
          example: Invalid parameter value
        request_id:
          type: string
          description: 唯一请求标识符。
          example: a3f4befe-cacd-49c9-8298-xxxxxx
````