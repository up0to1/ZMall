> ## Documentation Index
> Fetch the complete documentation index at: https://platform.qianwenai.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# 文本与多模态向量化

> 向量化模型可将文本、图像、视频等数据转换为数值向量，用于语义搜索、推荐、聚类、分类、异常检测等下游任务。

## 前提条件

[获取 API Key](/api-reference/preparation/api-key) 并[将其设置为环境变量](/api-reference/preparation/export-api-key-env)。如需使用 SDK，请先[安装 SDK](/api-reference/preparation/install-sdk)。

## 获取向量

### 文本向量化

调用 API 时，在请求中指定要向量化的文本和模型名称。

<Tabs>
  <Tab title="OpenAI 兼容">
    <CodeGroup>
      ```python Python
      import os
      from openai import OpenAI

      input_text = "The quality of the clothes is excellent"
    
      client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
      )
    
      completion = client.embeddings.create(
        model="text-embedding-v4",
        input=input_text
      )
    
      print(completion.model_dump_json())
      ```
    
      ```javascript Node.js
      const OpenAI = require("openai");
    
      const openai = new OpenAI({
        apiKey: process.env.DASHSCOPE_API_KEY,
        baseURL: 'https://dashscope.aliyuncs.com/compatible-mode/v1'
      });
    
      async function getEmbedding() {
        try {
          const inputTexts = "The quality of the clothes is excellent";
          const completion = await openai.embeddings.create({
            model: "text-embedding-v4",
            input: inputTexts,
            dimensions: 1024
          });
    
          console.log(JSON.stringify(completion, null, 2));
        } catch (error) {
          console.error('Error:', error);
        }
      }
    
      getEmbedding();
      ```
    
      ```bash curl
      curl --location 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings' \
      --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
      --header 'Content-Type: application/json' \
      --data '{
        "model": "text-embedding-v4",
        "input": "The quality of the clothes is excellent"
      }'
      ```
    </CodeGroup>
  </Tab>

  <Tab title="DashScope">
    <CodeGroup>
      ```python Python
      import dashscope
      from http import HTTPStatus

      dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
    
      input_text = "The quality of the clothes is excellent"
      resp = dashscope.TextEmbedding.call(
        model="text-embedding-v4",
        input=input_text,
      )
    
      if resp.status_code == HTTPStatus.OK:
        print(resp)
      ```
    
      ```java Java
      import com.alibaba.dashscope.embeddings.TextEmbedding;
      import com.alibaba.dashscope.embeddings.TextEmbeddingParam;
      import com.alibaba.dashscope.embeddings.TextEmbeddingResult;
      import com.alibaba.dashscope.exception.NoApiKeyException;
      import com.alibaba.dashscope.utils.Constants;
    
      import java.util.Collections;
    
      public class Main {
        static {
          Constants.baseHttpApiUrl="https://dashscope.aliyuncs.com/api/v1";
        }
        public static void main(String[] args) {
          String inputTexts = "The quality of the clothes is excellent";
          try {
            TextEmbeddingParam param = TextEmbeddingParam
                .builder()
                .model("text-embedding-v4")
                .texts(Collections.singleton(inputTexts))
                .build();
    
            TextEmbedding textEmbedding = new TextEmbedding();
            TextEmbeddingResult result = textEmbedding.call(param);
    
            System.out.println(result);
    
          } catch (NoApiKeyException e) {
            System.err.println("调用 API 时发生异常: " + e.getMessage());
            System.err.println("请检查 API Key 是否已正确配置。");
            e.printStackTrace();
          }
        }
      }
      ```
    
      ```bash curl
      curl --location 'https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding' \
      --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
      --header 'Content-Type: application/json' \
      --data '{
        "model": "text-embedding-v4",
        "input": {
          "texts": [
          "The quality of the clothes is excellent"
          ]
        }
      }'
      ```
    </CodeGroup>
  </Tab>
</Tabs>

### 多模态独立向量

为每种输入（文本、图像或视频）分别生成独立向量。适合为图片和文字标题各自建立索引。

<Note>
  多模态 Embedding 需使用 DashScope SDK 或 HTTP API，不支持 OpenAI 兼容接口。
</Note>

<Tabs>
  <Tab title="Python">
    ```python
    import dashscope
    import json
    import os

    image = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png"
    
    resp = dashscope.MultiModalEmbedding.call(
      api_key=os.getenv("DASHSCOPE_API_KEY"),
      model="tongyi-embedding-vision-plus",
      input=[{"image": image}],
    )
    
    print(json.dumps(resp.output, indent=4))
    ```
  </Tab>

  <Tab title="Java">
    ```java
    import com.alibaba.dashscope.embeddings.MultiModalEmbedding;
    import com.alibaba.dashscope.embeddings.MultiModalEmbeddingItemImage;
    import com.alibaba.dashscope.embeddings.MultiModalEmbeddingParam;
    import com.alibaba.dashscope.embeddings.MultiModalEmbeddingResult;
    import com.alibaba.dashscope.exception.ApiException;
    import com.alibaba.dashscope.exception.NoApiKeyException;
    import com.alibaba.dashscope.exception.UploadFileException;

    import java.util.Collections;
    
    public class Main {
      public static void main(String[] args) {
        try {
          MultiModalEmbedding embedding = new MultiModalEmbedding();
          MultiModalEmbeddingItemImage image = new MultiModalEmbeddingItemImage(
            "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png");
    
          MultiModalEmbeddingParam param = MultiModalEmbeddingParam.builder()
            .model("tongyi-embedding-vision-plus")
            .contents(Collections.singletonList(image))
            .build();
    
          MultiModalEmbeddingResult result = embedding.call(param);
          System.out.println(result);
    
        } catch (ApiException | NoApiKeyException | UploadFileException e) {
          System.err.println(e.getMessage());
        }
      }
    }
    ```
  </Tab>
</Tabs>

视频输入：将 `{"image": image}` 替换为 `{"video": video_url}`。

### 多模态融合向量

将多模态输入（文本 + 图片 + 视频）编码为 **1 个向量**。适合图文混合检索——例如输入一张衬衫图片加上文本"找相似但更年轻的款式"，模型将图像和文本指令融合为一个向量。

<Tabs>
  <Tab title="Python">
    ```python
    import dashscope
    import json
    import os

    text = "白色运动鞋，轻量透气"
    image = "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png"
    
    resp = dashscope.MultiModalEmbedding.call(
      api_key=os.getenv("DASHSCOPE_API_KEY"),
      model="qwen3-vl-embedding",
      input=[
        {"text": text},
        {"image": image},
      ],
      enable_fusion=True,
    )
    
    print(json.dumps(resp.output, indent=4))
    ```
  </Tab>

  <Tab title="Java (HTTP)">
    ```java
    import java.net.URI;
    import java.net.http.HttpClient;
    import java.net.http.HttpRequest;
    import java.net.http.HttpResponse;

    public class Main {
      public static void main(String[] args) throws Exception {
        String apiKey = System.getenv("DASHSCOPE_API_KEY");
        String requestBody = "{"
            + "\"model\": \"qwen3-vl-embedding\","
            + "\"input\": {"
            + "  \"contents\": ["
            + "    {\"text\": \"这是一段测试文本，用于生成多模态融合向量\"},"
            + "    {\"image\": \"https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png\"},"
            + "    {\"video\": \"https://help-static-aliyun-doc.aliyuncs.com/file-manage-files/zh-CN/20250107/lbcemt/new+video.mp4\"}"
            + "  ]"
            + "},"
            + "\"parameters\": {"
            + "  \"enable_fusion\": true"
            + "}"
            + "}";
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"))
            .header("Authorization", "Bearer " + apiKey)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(requestBody))
            .build();
        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        System.out.println(response.body());
      }
    }
    ```
  </Tab>
</Tabs>

#### 各模型的融合方式

| 模型                                       | 融合方式                                                     |
| ------------------------------------------ | ------------------------------------------------------------ |
| `qwen3-vl-embedding`                       | 添加 `enable_fusion=True` 参数                               |
| `qwen2.5-vl-embedding`                     | 默认即为融合模式，无需额外参数                               |
| `tongyi-embedding-vision-plus-2026-03-06`  | 将 text、image 放在同一个 content 对象中：`[{"text": ..., "image": ...}]` |
| `tongyi-embedding-vision-flash-2026-03-06` | 同上                                                         |

<Accordion title="tongyi-embedding-vision-plus-2026-03-06 融合示例">
  该模型通过将 text 和 image 放在**同一个 content 对象**中实现融合，无需 `enable_fusion` 参数。

  <CodeGroup>
    ```python Python
    import dashscope
    import json
    import os

    resp = dashscope.MultiModalEmbedding.call(
      api_key=os.getenv("DASHSCOPE_API_KEY"),
      model="tongyi-embedding-vision-plus-2026-03-06",
      input=[
        {"text": "白色运动鞋", "image": "https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png"}
      ],
      dimension=1152,
    )
    
    print(json.dumps(resp.output, indent=4))
    ```
    
    ```java Java（HTTP）
    import java.net.URI;
    import java.net.http.HttpClient;
    import java.net.http.HttpRequest;
    import java.net.http.HttpResponse;
    
    public class Main {
      public static void main(String[] args) throws Exception {
        String apiKey = System.getenv("DASHSCOPE_API_KEY");
        String requestBody = "{"
            + "\"model\": \"tongyi-embedding-vision-plus-2026-03-06\","
            + "\"input\": {"
            + "  \"contents\": ["
            + "    {"
            + "      \"text\": \"白色运动鞋，轻量透气，适合跑步和日常穿着\","
            + "      \"image\": \"https://dashscope.oss-cn-beijing.aliyuncs.com/images/256_1.png\""
            + "    }"
            + "  ]"
            + "},"
            + "\"parameters\": {"
            + "  \"dimension\": 1152"
            + "}"
            + "}";
        HttpClient client = HttpClient.newHttpClient();
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"))
            .header("Authorization", "Bearer " + apiKey)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(requestBody))
            .build();
        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        System.out.println(response.body());
      }
    }
    ```
  </CodeGroup>
</Accordion>

## 模型选择

### 文本向量

| **模型**                                                     | **向量维度**                                        | **批次大小** | **每批最大 Token 数** | **支持的语言**                                               |
| ------------------------------------------------------------ | --------------------------------------------------- | ------------ | --------------------- | ------------------------------------------------------------ |
| qwen3.7-text-embedding                                       | 2,560、2,048、1,536、1,024（默认）、768、512、256   | 20           | 128,000               | 中文、英语、西班牙语、法语、葡萄牙语、印尼语、日语、韩语、德语、俄语等201种主流语种与方言 |
| text-embedding-v4（属于 [Qwen3-Embedding](https://qwenlm.github.io/blog/qwen3-embedding/) 系列） | 2,048、1,536、1,024（默认）、768、512、256、128、64 | 10           | 33,000                | 100+ 种主流语言，包括中文、英文、西班牙语、法语、葡萄牙语、印尼语、日语、韩语、德语、俄语等 |
| text-embedding-v3                                            | 1,024（默认）、768、512、256、128、64               | 10           | 8,192                 | 50+ 种主流语言，包括中文、英文、西班牙语、法语、葡萄牙语、印尼语、日语、韩语、德语、俄语等 |
| text-embedding-v2                                            | 1,536                                               | 25           | 2,048                 | 中文、英语、西班牙语、法语、葡萄牙语、印尼语、日语、韩语、德语、俄语 |
| text-embedding-v1                                            | 1,536                                               | 25           | 2,048                 | 中文、英语、西班牙语、法语、葡萄牙语、印尼语                 |
| text-embedding-async-v2                                      | 1,536                                               | 100,000      | 2,048                 | 中文、英语、西班牙语、法语、葡萄牙语、印尼语、日语、韩语、德语、俄语 |
| text-embedding-async-v1                                      | 1,536                                               | 100,000      | 2,048                 | 中文、英语、西班牙语、法语、葡萄牙语、印尼语                 |

<Note>
  批次大小是指单次 API 调用中可处理的最大文本数量。例如，text-embedding-v4 的批次大小为 10，即单次请求最多可传入 10 条文本进行向量化，每条文本不超过 33,000 个 Token。此限制适用于：

  - 字符串数组输入：数组最多包含 10 个元素。
  - 文件输入：文本文件最多包含 10 行文本。
</Note>

### 多模态向量

| **模型**                                 | **向量维度**                                  | **文本长度限制** | **图片大小限制**                                | **视频大小限制**                     |
| ---------------------------------------- | --------------------------------------------- | ---------------- | ----------------------------------------------- | ------------------------------------ |
| qwen3-vl-embedding                       | 2560（默认）、2048、1536、1024、768、512、256 | 32,000 Token     | 单张不超过 10 MB                                | 不超过 50 MB                         |
| qwen2.5-vl-embedding                     | 2048、1024（默认）、768、512                  | 32,000 Token     | 单张不超过 5 MB                                 | 不超过 50 MB                         |
| tongyi-embedding-vision-plus-2026-03-06  | 1152（默认）、1024、512、256、128、64         | 1,024 Token      | 建议单张不超过 5 MB，最大 10 MB，支持最多 64 张 | 不超过 50 MB，编码类型为 H.264/H.265 |
| tongyi-embedding-vision-flash-2026-03-06 | 768（默认）、512、256、128、64                | 1,024 Token      | 建议单张不超过 5 MB，最大 10 MB，支持最多 64 张 | 不超过 50 MB，编码类型为 H.264/H.265 |
| tongyi-embedding-vision-plus             | 1152                                          | 1,024 Token      | 单张不超过 3 MB，支持最多 8 张                  | 不超过 10 MB                         |
| tongyi-embedding-vision-flash            | 768                                           | 1,024 Token      | 单张不超过 3 MB，支持最多 8 张                  | 不超过 10 MB                         |
| multimodal-embedding-v1                  | 1,024                                         | 512 Token        | 单张不超过 3 MB                                 | 不超过 10 MB                         |

<Note>
  只有文本数据？使用 text-embedding-v4——更快、更便宜、维度选择更多。多模态 Embedding 专为跨模态检索设计（文本+图片、文本+视频）。
</Note>

#### 输入与语种限制

**融合向量模型**

| **模型**             | **文本**                                                     | **图片**                                                     | **视频**                | **单次请求条数**                            |
| -------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ | ----------------------- | ------------------------------------------- |
| qwen3-vl-embedding   | 中、英、日、韩、法、德等 33 种语言（中文、日语、韩语、印尼语、越南语、泰语、英语、法语、德语、俄语、葡萄牙语、西班牙语、意大利语、瑞典语、丹麦语、捷克语、挪威语、荷兰语、芬兰语、土耳其语、波兰语、斯瓦希里语、罗马尼亚语、塞尔维亚语、希腊语、哈萨克语、乌兹别克语、宿务语、阿拉伯语、乌尔都语、波斯语、印地语/天城语、希伯来语） | JPEG、PNG、WEBP、BMP、TIFF、ICO、DIB、ICNS、SGI（URL 或 Base64） | MP4、AVI、MOV（仅 URL） | 总数不超过 20，图片不超过 10，视频不超过 1  |
| qwen2.5-vl-embedding | 中、英、日、韩、法、德等 11 种语言（中文、英语、日语、韩语、法语、德语、俄语、葡萄牙语、西班牙语、意大利语、印尼语） | JPEG、PNG、WEBP、BMP、TIFF、ICO、DIB、ICNS、SGI（URL 或 Base64） | MP4、AVI、MOV（仅 URL） | 图片、文本、视频、融合对象每种类型最多 1 次 |

**独立向量模型**

| **模型**                                 | **文本**                                                     | **图片**                                                     | **视频**                                           | **单次请求条数**                                     |
| ---------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ | -------------------------------------------------- | ---------------------------------------------------- |
| tongyi-embedding-vision-plus-2026-03-06  | 中、英、日、韩等超 30 种语言（中文、日语、韩语、印尼语、越南语、泰语、英语、法语、德语、俄语、葡萄牙语、西班牙语、意大利语、瑞典语、丹麦语、捷克语、挪威语、荷兰语、芬兰语、土耳其语、波兰语、斯瓦希里语、罗马尼亚语、塞尔维亚语、希腊语、哈萨克语、乌兹别克语、宿务语、阿拉伯语、乌尔都语、波斯语、印地语/天城语、希伯来语） | JPEG、PNG、WEBP、BMP、TIFF、ICO、DIB、ICNS、SGI（URL 或 Base64） | MP4、MPEG、MOV、MPG、WEBM、AVI、FLV、MKV（仅 URL） | 总数不超过 20，图片不超过 64，视频不超过 8           |
| tongyi-embedding-vision-flash-2026-03-06 | 中、英、日、韩等超 30 种语言（中文、日语、韩语、印尼语、越南语、泰语、英语、法语、德语、俄语、葡萄牙语、西班牙语、意大利语、瑞典语、丹麦语、捷克语、挪威语、荷兰语、芬兰语、土耳其语、波兰语、斯瓦希里语、罗马尼亚语、塞尔维亚语、希腊语、哈萨克语、乌兹别克语、宿务语、阿拉伯语、乌尔都语、波斯语、印地语/天城语、希伯来语） | JPEG、PNG、WEBP、BMP、TIFF、ICO、DIB、ICNS、SGI（URL 或 Base64） | MP4、MPEG、MOV、MPG、WEBM、AVI、FLV、MKV（仅 URL） | 总数不超过 20，图片不超过 64，视频不超过 8           |
| tongyi-embedding-vision-plus             | 中文与英文                                                   | JPG、PNG、BMP（URL 或 Base64）                               | MP4、MPEG、MOV、MPG、WEBM、AVI、FLV、MKV（仅 URL） | 无数量限制，Token 数不超过单批次上限                 |
| tongyi-embedding-vision-flash            | 中文与英文                                                   | JPG、PNG、BMP（URL 或 Base64）                               | MP4、MPEG、MOV、MPG、WEBM、AVI、FLV、MKV（仅 URL） | 无数量限制，Token 数不超过单批次上限                 |
| multimodal-embedding-v1                  | 中文与英文                                                   | JPG、PNG、BMP（URL 或 Base64）                               | MP4、MPEG、MOV、MPG、WEBM、AVI、FLV、MKV（仅 URL） | 总数不超过 20；图片、视频各最多 1 条，文本最多 20 条 |

## 核心功能

### 切换向量维度

`qwen3.7-text-embedding`、`text-embedding-v4`、`text-embedding-v3`、`tongyi-embedding-vision-plus-2026-03-06`、`tongyi-embedding-vision-flash-2026-03-06`、`qwen3-vl-embedding` 和 `qwen2.5-vl-embedding` 支持自定义向量维度。维度越高，保留的语义信息越丰富，但存储和计算开销也更大。

- **通用场景（推荐）**：1024 维在性能与成本之间取得了最佳平衡，适合大多数语义检索任务。
- **高精度场景**：对精度要求较高的领域，可选择 1536 或 2048 维。精度有一定提升，但存储和计算开销显著增加。
- **资源受限场景**：对成本敏感的场景，可选择 768 维或更低。资源消耗显著降低，但语义信息会有一定损失。

<Tabs>
  <Tab title="OpenAI 兼容">
    ```python
    import os
    from openai import OpenAI

    client = OpenAI(
      api_key=os.getenv("DASHSCOPE_API_KEY"),
      base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    
    resp = client.embeddings.create(
      model="text-embedding-v4",
      input=["I like it and will buy from here again"],
      # 设置向量维度为 256
      dimensions=256
    )
    print(f"Embedding dimensions: {len(resp.data[0].embedding)}")
    ```
  </Tab>

  <Tab title="DashScope">
    ```python
    import dashscope

    dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
    
    resp = dashscope.TextEmbedding.call(
      model="text-embedding-v4",
      input=["I like it and will buy from here again"],
      # 设置向量维度为 256
      dimension=256
    )
    
    print(f"Embedding dimensions: {len(resp.output['embeddings'][0]['embedding'])}")
    ```
  </Tab>
</Tabs>

### 区分查询文本与文档文本（text\_type）

<Note>
  该参数目前仅支持通过 DashScope SDK 和 API 启用。
</Note>

在搜索类任务中，对不同类型的内容进行针对性的向量化处理，可以充分发挥各自的作用，从而获得最佳检索效果。`text_type` 参数就是为此设计的：

- `text_type: 'query'`：用于用户输入的**查询文本**。模型生成的向量更具方向性，类似"标题"向量，专为"提问"和"检索"优化。
- `text_type: 'document'`（默认）：用于存储在数据库中的**文档文本**。模型生成的向量包含更全面的信息，类似"正文"向量，专为被检索优化。

使用短文本匹配长文本时，应区分 `query` 和 `document`。对于所有文本角色相同的任务（如聚类或分类），无需设置此参数。

### 使用指令提升效果（instruct）

<Note>
  该参数目前仅支持通过 DashScope SDK 和 API 启用。
</Note>

提供清晰的英文指令，可引导 `text-embedding-v4` 针对特定检索场景优化向量质量，有效提升精度。使用此功能时，需将 `text_type` 参数设置为 `query`。

```python
import dashscope

dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

# 场景：为搜索引擎构建文档向量时，可添加指令来优化检索的向量质量。
resp = dashscope.TextEmbedding.call(
  model="text-embedding-v4",
  input="Research papers on machine learning",
  text_type="query",
  instruct="Given a research paper query, retrieve relevant research paper"
)
```

### 稠密向量与稀疏向量

<Note>
  该参数目前仅支持通过 DashScope SDK 和 API 启用。
</Note>

`text-embedding-v4` 和 `text-embedding-v3` 支持三种向量输出类型，满足不同检索策略的需求。

| **向量类型（`output_type`）** | **核心优势**                                                 | **主要不足**                                       | **典型应用场景**                        |
| ----------------------------- | ------------------------------------------------------------ | -------------------------------------------------- | --------------------------------------- |
| dense                         | **深度语义理解**。能识别同义词和上下文，检索结果更相关。     | **计算和存储成本更高**。无法保证精确的关键词匹配。 | 语义搜索、AI 对话、内容推荐。           |
| sparse                        | **计算效率高**。专注于**精确关键词匹配**和快速过滤。         | **牺牲语义理解**。无法处理同义词或上下文。         | 日志检索、商品 SKU 搜索、精确信息过滤。 |
| dense\&sparse                 | 结合语义和关键词，获得最佳搜索效果。**生成成本相同**，API 调用开销与单向量模式一致。 | **存储需求大**。系统架构和检索逻辑更复杂。         | 高质量生产级混合搜索引擎。              |

## 使用示例

<Note>
  以下代码仅供演示。在生产环境中，应预先计算向量并存储到向量数据库中。检索时只需计算查询向量。
</Note>

### 语义搜索

通过计算查询与文档之间的向量相似度，实现精准的语义匹配。

```python
import dashscope
import numpy as np
from dashscope import TextEmbedding

dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

def cosine_similarity(a, b):
  """计算余弦相似度"""
  return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def semantic_search(query, documents, top_k=5):
  """执行语义搜索"""
  # 生成查询向量
  query_resp = TextEmbedding.call(
  model="text-embedding-v4",
  input=query,
  dimension=1024
  )
  query_embedding = query_resp.output['embeddings'][0]['embedding']

  # 生成文档向量
  doc_resp = TextEmbedding.call(
  model="text-embedding-v4",
  input=documents,
  dimension=1024
  )

  # 计算相似度
  similarities = []
  for i, doc_emb in enumerate(doc_resp.output['embeddings']):
    similarity = cosine_similarity(query_embedding, doc_emb['embedding'])
    similarities.append((i, similarity))

  # 排序并返回 top_k 结果
  similarities.sort(key=lambda x: x[1], reverse=True)
  return [(documents[i], sim) for i, sim in similarities[:top_k]]

# 使用示例
documents = [
  "Artificial intelligence is a branch of computer science",
  "Machine learning is an important method for achieving artificial intelligence",
  "Deep learning is a subfield of machine learning"
]
query = "What is AI?"
results = semantic_search(query, documents, top_k=2)
for doc, sim in results:
  print(f"Similarity: {sim:.3f}, Document: {doc}")
```

### 推荐系统

通过分析用户历史行为的向量，发现用户兴趣偏好并推荐相似内容。

```python
import dashscope
import numpy as np
from dashscope import TextEmbedding

dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

def cosine_similarity(a, b):
  """计算余弦相似度"""
  return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
def build_recommendation_system(user_history, all_items, top_k=10):
  """构建推荐系统"""
  # 生成用户历史向量
  history_resp = TextEmbedding.call(
  model="text-embedding-v4",
  input=user_history,
  dimension=1024
  )

  # 计算用户偏好向量（取均值）
  user_embedding = np.mean([
  emb['embedding'] for emb in history_resp.output['embeddings']
  ], axis=0)

  # 生成所有物品的向量
  items_resp = TextEmbedding.call(
  model="text-embedding-v4",
  input=all_items,
  dimension=1024
  )

  # 计算推荐得分
  recommendations = []
  for i, item_emb in enumerate(items_resp.output['embeddings']):
    score = cosine_similarity(user_embedding, item_emb['embedding'])
    recommendations.append((all_items[i], score))

  # 排序并返回推荐结果
  recommendations.sort(key=lambda x: x[1], reverse=True)
  return recommendations[:top_k]

# 使用示例
user_history = ["Science Fiction", "Action", "Suspense"]
all_movies = ["Future World", "Space Adventure", "Ancient War", "Romantic Journey", "Superhero"]
recommendations = build_recommendation_system(user_history, all_movies)
for movie, score in recommendations:
  print(f"Recommendation Score: {score:.3f}, Movie: {movie}")
```

### 文本聚类

通过分析文本向量之间的距离，自动将相似文本归为一组。

```python
# 需要安装 scikit-learn：pip install scikit-learn
import dashscope
import numpy as np
from sklearn.cluster import KMeans

dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

def cluster_texts(texts, n_clusters=2):
  """对一组文本进行聚类"""
  # 1. 获取所有文本的向量
  resp = dashscope.TextEmbedding.call(
  model="text-embedding-v4",
  input=texts,
  dimension=1024
  )
  embeddings = np.array([item['embedding'] for item in resp.output['embeddings']])

  # 2. 使用 KMeans 算法进行聚类
  kmeans = KMeans(n_clusters=n_clusters, random_state=0, n_init='auto').fit(embeddings)

  # 3. 整理并返回结果
  clusters = {i: [] for i in range(n_clusters)}
  for i, label in enumerate(kmeans.labels_):
    clusters[label].append(texts[i])
  return clusters

# 使用示例
documents_to_cluster = [
  "Mobile phone company A releases a new phone",
  "Search engine company B launches a new system",
  "World Cup final: Argentina vs. France",
  "China wins another gold medal at the Olympics",
  "A company releases its latest AI chip",
  "European Cup match report"
]
clusters = cluster_texts(documents_to_cluster, n_clusters=2)
for cluster_id, docs in clusters.items():
  print(f"--- Cluster {cluster_id} ---")
  for doc in docs:
    print(f"- {doc}")
```

### 文本分类

通过计算输入文本与预定义标签之间的向量相似度，无需预先标注样本即可识别和分类新类别。

```python
import dashscope
import numpy as np

dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

def cosine_similarity(a, b):
  """计算余弦相似度"""
  return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def classify_text_zero_shot(text, labels):
  """零样本文本分类"""
  # 1. 获取输入文本和所有标签的向量
  resp = dashscope.TextEmbedding.call(
  model="text-embedding-v4",
  input=[text] + labels,
  dimension=1024
  )
  embeddings = resp.output['embeddings']
  text_embedding = embeddings[0]['embedding']
  label_embeddings = [emb['embedding'] for emb in embeddings[1:]]

  # 2. 计算与每个标签的相似度
  scores = [cosine_similarity(text_embedding, label_emb) for label_emb in label_embeddings]

  # 3. 返回相似度最高的标签
  best_match_index = np.argmax(scores)
  return labels[best_match_index], scores[best_match_index]

# 使用示例
text_to_classify = "The fabric of this dress is comfortable and the style is nice"
possible_labels = ["Digital Products", "Apparel & Accessories", "Food & Beverage", "Home & Living"]

label, score = classify_text_zero_shot(text_to_classify, possible_labels)
print(f"Input text: '{text_to_classify}'")
print(f"Best matching category: '{label}' (Similarity: {score:.3f})")
```

### 异常检测

通过计算文本向量与正常样本向量中心之间的相似度，识别与正常模式显著不同的异常数据。

<Note>
  示例代码中的阈值仅用于演示。实际业务场景中，相似度的具体数值取决于数据内容和分布，没有固定阈值。请根据自己的数据集校准该值。
</Note>

```python
import dashscope
import numpy as np

dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

def cosine_similarity(a, b):
  """计算余弦相似度"""
  return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def detect_anomaly(new_comment, normal_comments, threshold=0.6):
  # 1. 将所有正常评论和新评论向量化
  all_texts = normal_comments + [new_comment]
  resp = dashscope.TextEmbedding.call(
  model="text-embedding-v4",
  input=all_texts,
  dimension=1024
  )
  embeddings = [item['embedding'] for item in resp.output['embeddings']]

  # 2. 计算正常评论的中心向量（均值）
  normal_embeddings = np.array(embeddings[:-1])
  normal_center_vector = np.mean(normal_embeddings, axis=0)

  # 3. 计算新评论与中心向量的相似度
  new_comment_embedding = np.array(embeddings[-1])
  similarity = cosine_similarity(new_comment_embedding, normal_center_vector)

  # 4. 判断是否为异常
  is_anomaly = similarity < threshold
  return is_anomaly, similarity

# 使用示例
normal_user_comments = [
  "Today's meeting was productive",
  "The project is progressing smoothly",
  "The new version will be released next week",
  "User feedback is positive"
]

test_comments = {
  "Normal comment": "The feature works as expected",
  "Anomaly - meaningless garbled text": "asdfghjkl zxcvbnm"
}

print("--- Anomaly Detection Example ---")
for desc, comment in test_comments.items():
  is_anomaly, score = detect_anomaly(comment, normal_user_comments)
  result = "Yes" if is_anomaly else "No"
  print(f"Comment: '{comment}'")
  print(f"Is anomaly: {result} (Similarity to normal samples: {score:.3f})\n")
```

## API 参考

- [OpenAI 兼容 Embedding API 详情](/api-reference/text-embedding/openai-embedding)
- [DashScope Embedding API 详情](/api-reference/text-embedding/dashscope-embedding)
- [多模态 Embedding API 详情](/api-reference/multimodal-embedding/dashscope-multimodal-embedding)

## 错误码

如果调用失败，请参阅[错误信息](/api-reference/preparation/error-messages)。

## 模型性能（MTEB/CMTEB）

- **MTEB**：Massive Text Embedding Benchmark，针对分类、聚类、检索等任务的通用能力综合评测。
- **CMTEB**：Chinese Massive Text Embedding Benchmark，专门针对中文文本的评测。
- 分数范围为 0 到 100，数值越高表示性能越好。

| **模型**                     | **MTEB** | **MTEB（检索任务）** | **CMTEB** | **CMTEB（检索任务）** |
| ---------------------------- | -------- | -------------------- | --------- | --------------------- |
| text-embedding-v3（512 维）  | 62.11    | 54.30                | 66.81     | 71.88                 |
| text-embedding-v3（768 维）  | 62.43    | 54.74                | 67.90     | 72.29                 |
| text-embedding-v3（1024 维） | 63.39    | 55.41                | 68.92     | 73.23                 |
| text-embedding-v4（512 维）  | 64.73    | 56.34                | 68.79     | 73.33                 |
| text-embedding-v4（1024 维） | 68.36    | 59.30                | 70.14     | 73.98                 |
| text-embedding-v4（2048 维） | 71.58    | 61.97                | 71.99     | 75.01                 |









> ## Documentation Index
> Fetch the complete documentation index at: https://platform.qianwenai.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# OpenAI 兼容文本向量

> OpenAI 兼容的文本向量接口

<Note>
  调用 API 前，请先[获取 API Key](/api-reference/preparation/api-key) 并[将其设置为环境变量](/api-reference/preparation/export-api-key-env)。如果使用 OpenAI SDK，请先[安装 SDK](/api-reference/preparation/install-sdk)。
</Note>

## 支持的模型

| 模型              | 向量维度                                         | 最大 Token 数 | 批量大小 | 语言支持        |
| ----------------- | ------------------------------------------------ | ------------- | -------- | --------------- |
| text-embedding-v4 | 2048、1536、1024（默认）、768、512、256、128、64 | 8,192         | 10       | 100+ 种主流语言 |
| text-embedding-v3 | 1024（默认）、768、512                           | 8,192         | 10       | 50+ 种语言      |

关于模型计费，请参见[模型市场](https://www.qianwenai.com/models)。

## 服务地址

`POST https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings`

SDK 使用 base URL 时无需包含 `/embeddings`。

## OpenAPI

````yaml post /compatible-mode/v1/embeddings
openapi: 3.1.0
info:
  title: 文本向量 API
  description: 文本向量模型 API 参考文档，支持 OpenAI 兼容协议和 DashScope 协议。
  version: 1.0.0
servers:
  - url: https://dashscope.aliyuncs.com
    description: 服务端点
security:
  - bearer: []
paths:
  /compatible-mode/v1/embeddings:
    post:
      operationId: createEmbeddingsOpenAI
      summary: 创建文本向量（OpenAI 兼容）
      description: 使用 OpenAI 兼容协议创建文本向量。
      security:
        - bearer: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/EmbeddingRequest"
      responses:
        "200":
          description: 请求成功
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/EmbeddingResponse"
        "400":
          description: 请求参数有误
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
      x-codeSamples:
        - lang: python
          label: 输入字符串
          source: |
            import os
            from openai import OpenAI

            client = OpenAI(
              api_key=os.getenv("DASHSCOPE_API_KEY"),  # 如未配置环境变量，请用您的 API Key 替换此处。
              base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )

            completion = client.embeddings.create(
              model="text-embedding-v4",
              input='The clothes are of good quality and look good, definitely worth the wait. I love them.',
              dimensions=1024,
              encoding_format="float"
            )

            print(completion.model_dump_json())
        - lang: java
          label: 输入字符串
          source: |
            import java.net.URI;
            import java.net.http.HttpClient;
            import java.net.http.HttpRequest;
            import java.net.http.HttpResponse;
            import java.util.HashMap;
            import java.util.Map;
            import com.alibaba.dashscope.utils.JsonUtils;

            public final class Main {
              public static void main(String[] args) {
                String apiKey = System.getenv("DASHSCOPE_API_KEY");
                if (apiKey == null) {
                  System.out.println("DASHSCOPE_API_KEY not found in environment variables");
                  return;
                }
                String baseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings";
                HttpClient client = HttpClient.newHttpClient();

                Map<String, Object> requestBody = new HashMap<>();
                requestBody.put("model", "text-embedding-v4");
                requestBody.put("input", "Semantic search finds documents by meaning rather than exact keyword matching. Text embeddings map words and sentences into high-dimensional vector spaces. Retrieval-augmented generation combines search results with language models. Document clustering groups similar texts based on their vector representations.");
                requestBody.put("dimensions", 1024);
                requestBody.put("encoding_format", "float");

                try {
                  String requestBodyString = JsonUtils.toJson(requestBody);
                  HttpRequest request = HttpRequest.newBuilder()
                      .uri(URI.create(baseUrl))
                      .header("Content-Type", "application/json")
                      .header("Authorization", "Bearer " + apiKey)
                      .POST(HttpRequest.BodyPublishers.ofString(requestBodyString))
                      .build();

                  HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
                  if (response.statusCode() == 200) {
                    System.out.println("Response: " + response.body());
                  } else {
                    System.out.printf("Failed to retrieve response, status code: %d, response: %s%n", response.statusCode(), response.body());
                  }
                } catch (Exception e) {
                  System.err.println("Error: " + e.getMessage());
                }
              }
            }
        - lang: bash
          label: 输入字符串
          source: |
            curl --location 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'Content-Type: application/json' \
            --data '{
              "model": "text-embedding-v4",
              "input": "Semantic search finds documents by meaning rather than exact keyword matching. Text embeddings map words and sentences into high-dimensional vector spaces. Retrieval-augmented generation combines search results with language models. Document clustering groups similar texts based on their vector representations.",
              "dimensions": 1024,
              "encoding_format": "float"
            }'
        - lang: python
          label: 输入字符串列表
          source: |-
            import os
            from openai import OpenAI

            client = OpenAI(
              api_key=os.getenv("DASHSCOPE_API_KEY"),  # 如未配置环境变量，请用您的 API Key 替换此处。
              base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )

            completion = client.embeddings.create(
              model="text-embedding-v4",
              input=['Semantic search finds documents by meaning rather than exact keyword matching.', 'Text embeddings map words and sentences into high-dimensional vector spaces.', 'Retrieval-augmented generation combines search results with language models.', 'Document clustering groups similar texts based on their vector representations.'],
              dimensions=1024,
              encoding_format="float"
            )

            print(completion.model_dump_json())
        - lang: java
          label: 输入字符串列表
          source: |
            import java.net.URI;
            import java.net.http.HttpClient;
            import java.net.http.HttpRequest;
            import java.net.http.HttpResponse;
            import java.util.HashMap;
            import java.util.Map;
            import java.util.List;
            import java.util.Arrays;
            import com.alibaba.dashscope.utils.JsonUtils;

            public final class Main {
              public static void main(String[] args) {
                /** 从环境变量中获取 API Key。如未配置，请用您的 API Key 替换此处。 */
                String apiKey = System.getenv("DASHSCOPE_API_KEY");
                if (apiKey == null) {
                  System.out.println("DASHSCOPE_API_KEY not found in environment variables");
                  return;
                }
                String baseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings";
                HttpClient client = HttpClient.newHttpClient();
                Map<String, Object> requestBody = new HashMap<>();
                requestBody.put("model", "text-embedding-v4");
                List<String> inputList = Arrays.asList("Semantic search finds documents by meaning rather than exact keyword matching.", "Text embeddings map words and sentences into high-dimensional vector spaces.", "Retrieval-augmented generation combines search results with language models.", "Document clustering groups similar texts based on their vector representations.");
                requestBody.put("input", inputList);
                requestBody.put("encoding_format", "float");

                try {
                  /** 将请求体转换为 JSON 字符串。 */
                  String requestBodyString = JsonUtils.toJson(requestBody);

                  /** 构建 HTTP 请求。 */
                  HttpRequest request = HttpRequest.newBuilder()
                      .uri(URI.create(baseUrl))
                      .header("Content-Type", "application/json")
                      .header("Authorization", "Bearer " + apiKey)
                      .POST(HttpRequest.BodyPublishers.ofString(requestBodyString))
                      .build();

                  /** 发送请求并接收响应。 */
                  HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
                  if (response.statusCode() == 200) {
                    System.out.println("Response: " + response.body());
                  } else {
                    System.out.printf("Failed to retrieve response, status code: %d, response: %s%n", response.statusCode(), response.body());
                  }
                } catch (Exception e) {
                  /** 捕获并打印异常。 */
                  System.err.println("Error: " + e.getMessage());
                }
              }
            }
        - lang: bash
          label: 输入字符串列表
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'Content-Type: application/json' \
            --data '{
              "model": "text-embedding-v4",
              "input": [
                "Semantic search finds documents by meaning rather than exact keyword matching.",
                "Text embeddings map words and sentences into high-dimensional vector spaces.",
                "Retrieval-augmented generation combines search results with language models.",
                "Document clustering groups similar texts based on their vector representations."
                ],
              "dimensions": 1024,
              "encoding_format": "float"
            }'
        - lang: python
          label: 输入文件
          source: |
            import os
            from openai import OpenAI

            client = OpenAI(
              api_key=os.getenv("DASHSCOPE_API_KEY"),  # 如未配置环境变量，请用您的 API Key 替换此处。
              base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            # 请将 'texts_to_embedding.txt' 替换为您自己的文件名或路径。
            with open('texts_to_embedding.txt', 'r', encoding='utf-8') as f:
              completion = client.embeddings.create(
                model="text-embedding-v4",
                input=f,
                encoding_format="float"
              )
            print(completion.model_dump_json())
        - lang: java
          label: 输入文件
          source: |
            import java.net.URI;
            import java.net.http.HttpClient;
            import java.net.http.HttpRequest;
            import java.net.http.HttpResponse;
            import java.util.HashMap;
            import java.util.Map;
            import java.io.BufferedReader;
            import java.io.FileReader;
            import java.io.IOException;
            import com.alibaba.dashscope.utils.JsonUtils;

            public class Main {
              public static void main(String[] args) {
                /** 从环境变量中获取 API Key。如未配置，请用您的 API Key 替换此处。 */
                String apiKey = System.getenv("DASHSCOPE_API_KEY");
                if (apiKey == null) {
                  System.out.println("DASHSCOPE_API_KEY not found in environment variables");
                  return;
                }
                String baseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings";
                HttpClient client = HttpClient.newHttpClient();

                /** 读取输入文件。 */
                StringBuilder inputText = new StringBuilder();
                try (BufferedReader reader = new BufferedReader(new FileReader("<path_to_your_content_root>"))) {
                  String line;
                  while ((line = reader.readLine()) != null) {
                    inputText.append(line).append("\n");
                  }
                } catch (IOException e) {
                  System.err.println("Error reading input file: " + e.getMessage());
                  return;
                }

                Map<String, Object> requestBody = new HashMap<>();
                requestBody.put("model", "text-embedding-v4");
                requestBody.put("input", inputText.toString().trim());
                requestBody.put("dimensions", 1024);
                requestBody.put("encoding_format", "float");

                try {
                  String requestBodyString = JsonUtils.toJson(requestBody);

                  /** 构建 HTTP 请求。 */
                  HttpRequest request = HttpRequest.newBuilder()
                      .uri(URI.create(baseUrl))
                      .header("Content-Type", "application/json")
                      .header("Authorization", "Bearer " + apiKey)
                      .POST(HttpRequest.BodyPublishers.ofString(requestBodyString))
                      .build();
                  HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
                  if (response.statusCode() == 200) {
                    System.out.println("Response: " + response.body());
                  } else {
                    System.out.printf("Failed to retrieve response, status code: %d, response: %s%n", response.statusCode(), response.body());
                  }
                } catch (Exception e) {
                  System.err.println("Error: " + e.getMessage());
                }
              }
            }
        - lang: bash
          label: 输入文件
          source: |-
            FILE_CONTENT=$(cat texts_to_embedding.txt | jq -Rs .)
            curl --location 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'Content-Type: application/json' \
            --data '{
              "model": "text-embedding-v4",
              "input": ['"$FILE_CONTENT"'],
              "dimensions": 1024,
              "encoding_format": "float"
            }'
components:
  securitySchemes:
    bearer:
      type: http
      scheme: bearer
      description: 千问 AI 平台 API Key。详见[获取 API Key](/api-reference/preparation/api-key)。
  schemas:
    EmbeddingRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 调用的模型名称，支持 `text-embedding-v4` 和 `text-embedding-v3`。
          example: text-embedding-v4
        input:
          description: 待处理的输入文本。支持字符串、字符串数组或文件。单个字符串最多包含 8,192 个 token；字符串列表或文件最多包含 10 条（行），每条最多 8,192 个 token。
          oneOf:
            - type: string
              description: 单个文本字符串。
            - type: array
              items:
                type: string
              description: 字符串数组（最多 10 条）。
        dimensions:
          type: integer
          description: 向量维度。可选值：2048（仅 text-embedding-v4）、1536（仅 text-embedding-v4）、1024、768、512、256（仅 text-embedding-v4）、128（仅 text-embedding-v4）、64（仅 text-embedding-v4）。默认值：1024。
          default: 1024
          enum:
            - 2048
            - 1536
            - 1024
            - 768
            - 512
            - 256
            - 128
            - 64
        encoding_format:
          type: string
          description: 返回向量的格式，目前仅支持 `float`。
          default: float
          enum:
            - float
    EmbeddingResponse:
      type: object
      properties:
        data:
          type: array
          description: 任务输出数据。
          items:
            type: object
            properties:
              embedding:
                type: array
                items:
                  type: number
                description: 向量表示，为浮点数数组。
              index:
                type: integer
                description: 本结果对应输入数组中的文本索引。
              object:
                type: string
                description: 调用返回的对象类型，默认为 `embedding`。
                default: embedding
        model:
          type: string
          description: 调用的模型名称。
        object:
          type: string
          description: 返回的数据类型，默认为 `list`。
          default: list
        usage:
          type: object
          description: Token 用量统计。
          properties:
            prompt_tokens:
              type: integer
              description: 输入文本的 token 数量。
            total_tokens:
              type: integer
              description: 请求中 token 的总数，按模型分词器计算。
        id:
          type: string
          description: 请求的唯一标识符，可用于追踪和排查问题。
      example:
        data:
          - embedding:
              - -0.0695386752486229
              - 0.030681096017360687
            index: 0
            object: embedding
          - embedding:
              - -0.06348952651023865
              - 0.060446035116910934
            index: 5
            object: embedding
        model: text-embedding-v4
        object: list
        usage:
          prompt_tokens: 184
          total_tokens: 184
        id: 73591b79-d194-9bca-8bb5-xxxxxxxxxxxx
    DashScopeEmbeddingRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 调用的模型名称，支持 `text-embedding-v4` 和 `text-embedding-v3`。
          example: text-embedding-v4
        input:
          type: object
          required:
            - texts
          description: 包含待向量化文本的输入对象。
          properties:
            texts:
              description: 待处理的输入文本，可以是字符串或字符串数组。单个字符串最多 8,192 个 token；字符串列表最多 10 条，每条最多 8,192 个 token。
              oneOf:
                - type: string
                  description: 单个文本字符串。
                - type: array
                  items:
                    type: string
                  description: 字符串数组（最多 10 条）。
        parameters:
          type: object
          description: 向量化请求的可选参数。
          properties:
            text_type:
              type: string
              description: 指定文本类型，用于非对称任务。检索场景下区分 `query`（查询词）和 `document`（文档）有助于提升效果；聚类、分类等对称任务使用默认值 `document`。
              default: document
              enum:
                - query
                - document
            dimension:
              type: integer
              description: 向量维度。可选值：2048（仅 text-embedding-v4）、1536（仅 text-embedding-v4）、1024、768、512、256（仅 text-embedding-v4）、128（仅 text-embedding-v4）、64（仅 text-embedding-v4）。默认值：1024。
              default: 1024
              enum:
                - 2048
                - 1536
                - 1024
                - 768
                - 512
                - 256
                - 128
                - 64
            output_type:
              type: string
              description: 是否输出稀疏向量表示，仅适用于 text-embedding-v3 和 text-embedding-v4。默认值：`dense`（仅返回稠密向量）。
              default: dense
              enum:
                - dense
                - sparse
                - dense&sparse
            instruct:
              type: string
              description: 自定义任务描述，仅在 text-embedding-v4 且 `text_type` 为 `query` 时生效，推荐使用英文描述（可提升约 1%~5% 的效果）。
    DashScopeEmbeddingResponse:
      type: object
      properties:
        status_code:
          type: integer
          description: 状态码，200 表示请求成功。
        request_id:
          type: string
          description: 请求的唯一标识符，可用于追踪和排查问题。
        code:
          type: string
          description: 请求失败时的错误码，成功时为空。
        message:
          type: string
          description: 请求失败时的详细错误信息，成功时为空。
        output:
          type: object
          description: 任务输出数据。
          properties:
            embeddings:
              type: array
              description: 结构体数组，每个结构体包含对应输入文本的向量输出。
              items:
                type: object
                properties:
                  sparse_embedding:
                    type: array
                    description: 稀疏向量表示，仅在 `output_type` 包含 `sparse` 时适用于 text-embedding-v3 和 text-embedding-v4。
                    items:
                      type: object
                      properties:
                        index:
                          type: integer
                          description: 词或字符在词汇表中的索引。
                        value:
                          type: number
                          description: 该 token 的权重或重要性分数，值越高表示越重要。
                        token:
                          type: string
                          description: 来自词汇表的实际文本单元或词语。
                  embedding:
                    type: array
                    items:
                      type: number
                    description: 稠密向量表示（dense embedding）。
                  text_index:
                    type: integer
                    description: 本结果对应输入数组中的文本索引。
        usage:
          type: object
          description: Token 用量统计。
          properties:
            total_tokens:
              type: integer
              description: 请求中 token 的总数，按模型分词器计算。
      example:
        status_code: 200
        request_id: 1ba94ac8-e058-99bc-9cc1-7fdb37940a46
        code: ""
        message: ""
        output:
          embeddings:
            - sparse_embedding:
                - index: 7149
                  value: 0.829
                  token: wind
                - index: 111290
                  value: 0.9004
                  token: sorrow
              embedding:
                - -0.006929283495992422
                - -0.005336422007530928
              text_index: 0
        usage:
          total_tokens: 27
    ErrorResponse:
      type: object
      properties:
        code:
          type: string
          description: 错误码。
        message:
          type: string
          description: 详细错误信息。
        request_id:
          type: string
          description: 请求的唯一标识符，可用于追踪和排查问题。
      example:
        code: InvalidParameter
        message: "The model name is invalid. Supported models: text-embedding-v4, text-embedding-v3."
        request_id: a1b2c3d4-e5f6-7890-abcd-xxxxxxxxxxxx
````









> ## Documentation Index
> Fetch the complete documentation index at: https://platform.qianwenai.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# DashScope 文本向量

> DashScope embedding API

将文本转换为向量，用于语义搜索、推荐、聚类和分类。

<Note>
  开始之前：[获取 API Key](/api-reference/preparation/api-key)，[将其设置为环境变量](/api-reference/preparation/export-api-key-env)，如果使用 SDK，还需[安装 DashScope SDK](/api-reference/preparation/install-sdk)。
</Note>

## 设置 SDK 基础 URL

**Python SDK**：

```python
import dashscope
dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
```

**Java SDK**：

```java
import com.alibaba.dashscope.utils.Constants;
Constants.baseHttpApiUrl = "https://dashscope.aliyuncs.com/api/v1";
```

## 支持的模型

| 模型              | 向量维度                                         | 最大 Token 数 | 批量大小 | 语言支持 |
| ----------------- | ------------------------------------------------ | ------------- | -------- | -------- |
| text-embedding-v4 | 2048、1536、1024（默认）、768、512、256、128、64 | 8,192         | 10       | 100+ 种  |
| text-embedding-v3 | 1024（默认）、768、512                           | 8,192         | 10       | 50+ 种   |

关于模型计费，请参见[模型市场](https://www.qianwenai.com/models)。

## 输入格式

- **单个字符串**：最多 8,192 个 Token
- **数组**：最多 10 个字符串，每个最多 8,192 个 Token
- **文本文件**：最多 10 行，每行最多 8,192 个 Token

## DashScope 特有功能

- `text_type`：设置为 `query` 或 `document`，适用于检索等非对称任务。
- `output_type`：返回稀疏向量（`dense&sparse`），用于混合搜索（仅 v3/v4 支持）。
- `instruct`：添加任务描述以提升准确率约 1-5%（仅 v4 支持；建议使用英文）。

参见[限流](/developer-guides/administration/rate-limits)。

## OpenAPI

````yaml post /api/v1/services/embeddings/text-embedding/text-embedding
openapi: 3.1.0
info:
  title: 文本向量 API
  description: 文本向量模型 API 参考文档，支持 OpenAI 兼容协议和 DashScope 协议。
  version: 1.0.0
servers:
  - url: https://dashscope.aliyuncs.com
    description: 服务端点
security:
  - bearer: []
paths:
  /api/v1/services/embeddings/text-embedding/text-embedding:
    post:
      operationId: createEmbeddingsDashScope
      summary: 创建文本向量（DashScope）
      description: 使用 DashScope 协议创建文本向量。
      security:
        - bearer: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/DashScopeEmbeddingRequest"
      responses:
        "200":
          description: 请求成功
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/DashScopeEmbeddingResponse"
        "400":
          description: 请求参数有误
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
      x-codeSamples:
        - lang: python
          label: 输入字符串
          source: |
            import dashscope
            from http import HTTPStatus

            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

            resp = dashscope.TextEmbedding.call(
              model=dashscope.TextEmbedding.Models.text_embedding_v4,
              input='Semantic search finds documents by meaning rather than exact keyword matching. Text embeddings map words and sentences into high-dimensional vector spaces. Retrieval-augmented generation combines search results with language models. Document clustering groups similar texts based on their vector representations.',
              dimension=1024,
              output_type="dense&sparse"
            )

            print(resp) if resp.status_code == HTTPStatus.OK else print(resp)
        - lang: java
          label: 输入字符串
          source: |-
            import java.util.Arrays;
            import java.util.concurrent.Semaphore;
            import com.alibaba.dashscope.common.ResultCallback;
            import com.alibaba.dashscope.embeddings.TextEmbedding;
            import com.alibaba.dashscope.embeddings.TextEmbeddingParam;
            import com.alibaba.dashscope.embeddings.TextEmbeddingResult;
            import com.alibaba.dashscope.exception.ApiException;
            import com.alibaba.dashscope.exception.NoApiKeyException;
            import com.alibaba.dashscope.utils.Constants;

            public final class Main {
                static {
                    Constants.baseHttpApiUrl="https://dashscope.aliyuncs.com/api/v1";
                }
                public static void basicCall() throws ApiException, NoApiKeyException{
                    TextEmbeddingParam param = TextEmbeddingParam
                    .builder()
                    .model(TextEmbedding.Models.TEXT_EMBEDDING_V4)
                    .texts(Arrays.asList("Semantic search finds documents by meaning rather than exact keyword matching.", "Text embeddings map words and sentences into high-dimensional vector spaces.", "Retrieval-augmented generation combines search results with language models.", "Document clustering groups similar texts based on their vector representations.")).build();
                    TextEmbedding textEmbedding = new TextEmbedding();
                    TextEmbeddingResult result = textEmbedding.call(param);
                    System.out.println(result);
                }

                public static void callWithCallback() throws ApiException, NoApiKeyException, InterruptedException{
                    TextEmbeddingParam param = TextEmbeddingParam
                    .builder()
                    .model(TextEmbedding.Models.TEXT_EMBEDDING_V4)
                    .texts(Arrays.asList("Semantic search finds documents by meaning rather than exact keyword matching.", "Text embeddings map words and sentences into high-dimensional vector spaces.", "Retrieval-augmented generation combines search results with language models.", "Document clustering groups similar texts based on their vector representations.")).build();
                    TextEmbedding textEmbedding = new TextEmbedding();
                    Semaphore sem = new Semaphore(0);
                    textEmbedding.call(param, new ResultCallback<TextEmbeddingResult>() {

                      @Override
                      public void onEvent(TextEmbeddingResult message) {
                        System.out.println(message);
                      }
                      @Override
                      public void onComplete(){
                        sem.release();
                      }

                      @Override
                      public void onError(Exception err){
                        System.out.println(err.getMessage());
                        err.printStackTrace();
                        sem.release();
                      }

                    });
                    sem.acquire();
                }

              public static void main(String[] args){
                try{
                  callWithCallback();
                }catch(ApiException|NoApiKeyException|InterruptedException e){
                  e.printStackTrace();
                  System.out.println(e);

                }
                  try {
                    basicCall();
                } catch (ApiException | NoApiKeyException e) {
                    System.out.println(e.getMessage());
                }
                System.exit(0);
              }
            }
        - lang: bash
          label: 输入字符串
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'Content-Type: application/json' \
            --data '{
              "model": "text-embedding-v4",
              "input": {
                "texts": [
                "Semantic search finds documents by meaning rather than exact keyword matching. Text embeddings map words and sentences into high-dimensional vector spaces. Retrieval-augmented generation combines search results with language models. Document clustering groups similar texts based on their vector representations."
                ]
              },
              "parameters": {
                "dimension": 1024,
                "output_type": "dense"
              }
            }'
        - lang: python
          label: 输入字符串列表
          source: |
            import dashscope
            from http import HTTPStatus

            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
            DASHSCOPE_MAX_BATCH_SIZE = 10

            inputs = ['Semantic search finds documents by meaning rather than exact keyword matching.', 'Text embeddings map words and sentences into high-dimensional vector spaces.', 'Retrieval-augmented generation combines search results with language models.', 'Document clustering groups similar texts based on their vector representations.']

            result = None
            batch_counter = 0
            for i in range(0, len(inputs), DASHSCOPE_MAX_BATCH_SIZE):
              batch = inputs[i:i + DASHSCOPE_MAX_BATCH_SIZE]
              resp = dashscope.TextEmbedding.call(
                model=dashscope.TextEmbedding.Models.text_embedding_v4,
                input=batch,
                dimension=1024
              )
              if resp.status_code == HTTPStatus.OK:
                if result is None:
                  result = resp
                else:
                  for emb in resp.output['embeddings']:
                    emb['text_index'] += batch_counter
                    result.output['embeddings'].append(emb)
                  result.usage['total_tokens'] += resp.usage['total_tokens']
              else:
                print(resp)
              batch_counter += len(batch)

            print(result)
        - lang: java
          label: 输入字符串列表
          source: |
            import java.util.Arrays;
            import java.util.List;
            import com.alibaba.dashscope.embeddings.TextEmbedding;
            import com.alibaba.dashscope.embeddings.TextEmbeddingParam;
            import com.alibaba.dashscope.embeddings.TextEmbeddingResult;
            import com.alibaba.dashscope.exception.ApiException;
            import com.alibaba.dashscope.exception.NoApiKeyException;
            import com.alibaba.dashscope.utils.Constants;

            public final class Main {
              static {
                Constants.baseHttpApiUrl="https://dashscope.aliyuncs.com/api/v1";
              }
              private static final int DASHSCOPE_MAX_BATCH_SIZE = 10;

              public static void main(String[] args) {
                List<String> inputs = Arrays.asList(
                    "Semantic search finds documents by meaning rather than exact keyword matching.",
                    "Text embeddings map words and sentences into high-dimensional vector spaces.",
                    "Retrieval-augmented generation combines search results with language models.",
                    "Document clustering groups similar texts based on their vector representations."
                );

                TextEmbeddingResult result = null;
                int batchCounter = 0;

                for (int i = 0; i < inputs.size(); i += DASHSCOPE_MAX_BATCH_SIZE) {
                  List<String> batch = inputs.subList(i, Math.min(i + DASHSCOPE_MAX_BATCH_SIZE, inputs.size()));
                  TextEmbeddingParam param = TextEmbeddingParam.builder()
                      .model(TextEmbedding.Models.TEXT_EMBEDDING_V4)
                      .texts(batch)
                      .build();

                  TextEmbedding textEmbedding = new TextEmbedding();
                  try {
                    TextEmbeddingResult resp = textEmbedding.call(param);
                    if (resp != null) {
                      if (result == null) {
                        result = resp;
                      } else {
                        for (var emb : resp.getOutput().getEmbeddings()) {
                          emb.setTextIndex(emb.getTextIndex() + batchCounter);
                          result.getOutput().getEmbeddings().add(emb);
                        }
                        result.getUsage().setTotalTokens(result.getUsage().getTotalTokens() + resp.getUsage().getTotalTokens());
                      }
                    } else {
                      System.out.println(resp);
                    }
                  } catch (ApiException | NoApiKeyException e) {
                    e.printStackTrace();
                  }
                  batchCounter += batch.size();
                }

                System.out.println(result);
              }
            }
        - lang: bash
          label: 输入字符串列表
          source: |-
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'Content-Type: application/json' \
            --data '{
              "model": "text-embedding-v4",
              "input": {
              "texts": [
                      "Semantic search finds documents by meaning rather than exact keyword matching.",
                      "Text embeddings map words and sentences into high-dimensional vector spaces.",
                      "Retrieval-augmented generation combines search results with language models.",
                      "Document clustering groups similar texts based on their vector representations."
              ]
              },
              "parameters": {
                	  "dimension": 1024,
                	  "output_type": "dense"
              }
            }'
        - lang: python
          label: 输入文件
          source: |
            import dashscope
            from http import HTTPStatus
            from dashscope import TextEmbedding

            dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'
            # 请将 'texts_to_embedding.txt' 替换为您自己的文件名或路径。
            with open('texts_to_embedding.txt', 'r', encoding='utf-8') as f:
              resp = TextEmbedding.call(
                model=TextEmbedding.Models.text_embedding_v4,
                input=f,
                dimension=1024
              )

              if resp.status_code == HTTPStatus.OK:
                print(resp)
              else:
                print(resp)
        - lang: java
          label: 输入文件
          source: |-
            import java.io.BufferedReader;
            import java.io.FileReader;
            import java.io.IOException;
            import com.alibaba.dashscope.embeddings.TextEmbedding;
            import com.alibaba.dashscope.embeddings.TextEmbeddingParam;
            import com.alibaba.dashscope.embeddings.TextEmbeddingResult;
            import com.alibaba.dashscope.exception.ApiException;
            import com.alibaba.dashscope.exception.NoApiKeyException;
            import com.alibaba.dashscope.utils.Constants;

            public final class Main {
              static {
                Constants.baseHttpApiUrl="https://dashscope.aliyuncs.com/api/v1";
              }
              public static void main(String[] args) {
                // 请将 'tests_to_embedding.txt' 替换为您文件的完整路径。
                try (BufferedReader reader = new BufferedReader(new FileReader("texts_to_embedding.txt"))) {
                  StringBuilder content = new StringBuilder();
                  String line;
                  while ((line = reader.readLine()) != null) {
                    content.append(line).append("\n");
                  }

                  TextEmbeddingParam param = TextEmbeddingParam.builder()
                      .model(TextEmbedding.Models.TEXT_EMBEDDING_V4)
                      .text(content.toString())
                      .build();

                  TextEmbedding textEmbedding = new TextEmbedding();
                  TextEmbeddingResult result = textEmbedding.call(param);

                  if (result != null) {
                    System.out.println(result);
                  } else {
                    System.out.println("Failed to get embedding: " + result);
                  }
                } catch (IOException | ApiException | NoApiKeyException e) {
                  e.printStackTrace();
                }
              }
            }
        - lang: bash
          label: 输入文件
          source: |
            FILE_CONTENT=$(cat texts_to_embedding.txt | jq -Rs .)
            curl --location 'https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'Content-Type: application/json' \
            --data '{
              "model": "text-embedding-v4",
              "input": {
                "texts": ['"$FILE_CONTENT"']
              },
              "parameters": {
                "dimension": 1024,
                "output_type": "dense"
              }
            }'
components:
  securitySchemes:
    bearer:
      type: http
      scheme: bearer
      description: 千问 AI 平台 API Key。详见[获取 API Key](/api-reference/preparation/api-key)。
  schemas:
    EmbeddingRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 调用的模型名称，支持 `text-embedding-v4` 和 `text-embedding-v3`。
          example: text-embedding-v4
        input:
          description: 待处理的输入文本。支持字符串、字符串数组或文件。单个字符串最多包含 8,192 个 token；字符串列表或文件最多包含 10 条（行），每条最多 8,192 个 token。
          oneOf:
            - type: string
              description: 单个文本字符串。
            - type: array
              items:
                type: string
              description: 字符串数组（最多 10 条）。
        dimensions:
          type: integer
          description: 向量维度。可选值：2048（仅 text-embedding-v4）、1536（仅 text-embedding-v4）、1024、768、512、256（仅 text-embedding-v4）、128（仅 text-embedding-v4）、64（仅 text-embedding-v4）。默认值：1024。
          default: 1024
          enum:
            - 2048
            - 1536
            - 1024
            - 768
            - 512
            - 256
            - 128
            - 64
        encoding_format:
          type: string
          description: 返回向量的格式，目前仅支持 `float`。
          default: float
          enum:
            - float
    EmbeddingResponse:
      type: object
      properties:
        data:
          type: array
          description: 任务输出数据。
          items:
            type: object
            properties:
              embedding:
                type: array
                items:
                  type: number
                description: 向量表示，为浮点数数组。
              index:
                type: integer
                description: 本结果对应输入数组中的文本索引。
              object:
                type: string
                description: 调用返回的对象类型，默认为 `embedding`。
                default: embedding
        model:
          type: string
          description: 调用的模型名称。
        object:
          type: string
          description: 返回的数据类型，默认为 `list`。
          default: list
        usage:
          type: object
          description: Token 用量统计。
          properties:
            prompt_tokens:
              type: integer
              description: 输入文本的 token 数量。
            total_tokens:
              type: integer
              description: 请求中 token 的总数，按模型分词器计算。
        id:
          type: string
          description: 请求的唯一标识符，可用于追踪和排查问题。
      example:
        data:
          - embedding:
              - -0.0695386752486229
              - 0.030681096017360687
            index: 0
            object: embedding
          - embedding:
              - -0.06348952651023865
              - 0.060446035116910934
            index: 5
            object: embedding
        model: text-embedding-v4
        object: list
        usage:
          prompt_tokens: 184
          total_tokens: 184
        id: 73591b79-d194-9bca-8bb5-xxxxxxxxxxxx
    DashScopeEmbeddingRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 调用的模型名称，支持 `text-embedding-v4` 和 `text-embedding-v3`。
          example: text-embedding-v4
        input:
          type: object
          required:
            - texts
          description: 包含待向量化文本的输入对象。
          properties:
            texts:
              description: 待处理的输入文本，可以是字符串或字符串数组。单个字符串最多 8,192 个 token；字符串列表最多 10 条，每条最多 8,192 个 token。
              oneOf:
                - type: string
                  description: 单个文本字符串。
                - type: array
                  items:
                    type: string
                  description: 字符串数组（最多 10 条）。
        parameters:
          type: object
          description: 向量化请求的可选参数。
          properties:
            text_type:
              type: string
              description: 指定文本类型，用于非对称任务。检索场景下区分 `query`（查询词）和 `document`（文档）有助于提升效果；聚类、分类等对称任务使用默认值 `document`。
              default: document
              enum:
                - query
                - document
            dimension:
              type: integer
              description: 向量维度。可选值：2048（仅 text-embedding-v4）、1536（仅 text-embedding-v4）、1024、768、512、256（仅 text-embedding-v4）、128（仅 text-embedding-v4）、64（仅 text-embedding-v4）。默认值：1024。
              default: 1024
              enum:
                - 2048
                - 1536
                - 1024
                - 768
                - 512
                - 256
                - 128
                - 64
            output_type:
              type: string
              description: 是否输出稀疏向量表示，仅适用于 text-embedding-v3 和 text-embedding-v4。默认值：`dense`（仅返回稠密向量）。
              default: dense
              enum:
                - dense
                - sparse
                - dense&sparse
            instruct:
              type: string
              description: 自定义任务描述，仅在 text-embedding-v4 且 `text_type` 为 `query` 时生效，推荐使用英文描述（可提升约 1%~5% 的效果）。
    DashScopeEmbeddingResponse:
      type: object
      properties:
        status_code:
          type: integer
          description: 状态码，200 表示请求成功。
        request_id:
          type: string
          description: 请求的唯一标识符，可用于追踪和排查问题。
        code:
          type: string
          description: 请求失败时的错误码，成功时为空。
        message:
          type: string
          description: 请求失败时的详细错误信息，成功时为空。
        output:
          type: object
          description: 任务输出数据。
          properties:
            embeddings:
              type: array
              description: 结构体数组，每个结构体包含对应输入文本的向量输出。
              items:
                type: object
                properties:
                  sparse_embedding:
                    type: array
                    description: 稀疏向量表示，仅在 `output_type` 包含 `sparse` 时适用于 text-embedding-v3 和 text-embedding-v4。
                    items:
                      type: object
                      properties:
                        index:
                          type: integer
                          description: 词或字符在词汇表中的索引。
                        value:
                          type: number
                          description: 该 token 的权重或重要性分数，值越高表示越重要。
                        token:
                          type: string
                          description: 来自词汇表的实际文本单元或词语。
                  embedding:
                    type: array
                    items:
                      type: number
                    description: 稠密向量表示（dense embedding）。
                  text_index:
                    type: integer
                    description: 本结果对应输入数组中的文本索引。
        usage:
          type: object
          description: Token 用量统计。
          properties:
            total_tokens:
              type: integer
              description: 请求中 token 的总数，按模型分词器计算。
      example:
        status_code: 200
        request_id: 1ba94ac8-e058-99bc-9cc1-7fdb37940a46
        code: ""
        message: ""
        output:
          embeddings:
            - sparse_embedding:
                - index: 7149
                  value: 0.829
                  token: wind
                - index: 111290
                  value: 0.9004
                  token: sorrow
              embedding:
                - -0.006929283495992422
                - -0.005336422007530928
              text_index: 0
        usage:
          total_tokens: 27
    ErrorResponse:
      type: object
      properties:
        code:
          type: string
          description: 错误码。
        message:
          type: string
          description: 详细错误信息。
        request_id:
          type: string
          description: 请求的唯一标识符，可用于追踪和排查问题。
      example:
        code: InvalidParameter
        message: "The model name is invalid. Supported models: text-embedding-v4, text-embedding-v3."
        request_id: a1b2c3d4-e5f6-7890-abcd-xxxxxxxxxxxx
````





> ## Documentation Index
> Fetch the complete documentation index at: https://platform.qianwenai.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# DashScope 多模态向量

> 多模态向量化 API

将文本、图像和视频转换为统一语义空间中的数值向量，用于跨模态检索、相似度搜索和内容分类。

<Note>
  开始前：[获取 API Key](/api-reference/preparation/api-key)，[将其设置为环境变量](/api-reference/preparation/export-api-key-env)，如需使用 SDK 请先[安装 DashScope SDK](/api-reference/preparation/install-sdk)。
</Note>

## 请求地址

- HTTP：`POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding`
- SDK `base_http_api_url`：`https://dashscope.aliyuncs.com/api/v1`

## 模型概览

| 模型                          | 支持模态               | 向量维度                              | 单张图片大小 |
| ----------------------------- | ---------------------- | ------------------------------------- | ------------ |
| tongyi-embedding-vision-plus  | 文本、图像、视频、多图 | 64、128、256、512、1024、1152（默认） | 10 MB        |
| tongyi-embedding-vision-flash | 文本、图像、视频、多图 | 64、128、256、512、768（默认）        | 5 MB         |

## 使用说明

- **图像输入**：公网 URL 或 Base64 数据 URI（`data:image/{format};base64,{data}`）。
- **多图输入**：使用 `multi_images` 字段，值为图像 URL 列表，最多 8 张。
- **视频输入**：必须为公网 URL。通过 `parameters` 中的 `fps` 参数控制采样帧率（取值范围 \[0, 1]，默认 1.0）。

## OpenAPI

````yaml post /services/embeddings/multimodal-embedding/multimodal-embedding
openapi: 3.1.0
info:
  title: 千问 AI 平台图像 API
  description: DashScope 图像 API，涵盖图像生成、图像编辑、专项图像任务及多模态向量嵌入。
  version: 1.0.0
servers:
  - url: https://dashscope.aliyuncs.com/api/v1
    description: DashScope API
security:
  - BearerAuth: []
paths:
  /services/embeddings/multimodal-embedding/multimodal-embedding:
    post:
      operationId: createMultimodalEmbedding
      summary: 创建多模态向量嵌入
      description: 将文本、图像和视频映射到统一向量空间。适用于跨模态检索、语义相似度计算、内容分类等场景。所有模态共享同一语义空间，可直接通过余弦相似度跨模态比较向量。
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/MultimodalEmbeddingRequest"
      responses:
        "200":
          description: 多模态向量嵌入结果
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/MultimodalEmbeddingResponse"
        "400":
          description: 请求参数无效
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/DashScopeErrorResponse"
        "401":
          description: 认证失败——API Key 无效或未提供
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/DashScopeErrorResponse"
        "429":
          description: 请求频率超出限制
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/DashScopeErrorResponse"
      x-codeSamples:
        - lang: curl
          label: cURL (Independent Vectors)
          source: |-
            curl --location --request POST \
              'https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'Content-Type: application/json' \
            --data '{
                "model": "tongyi-embedding-vision-plus",
                "input": {
                    "contents": [
                        {"text": "Multimodal embedding model"},
                        {"image": "https://example.com/image.jpg"},
                        {"video": "https://example.com/video.mp4"}
                    ]
                }
            }'
        - lang: curl
          label: cURL (Fused Vector)
          source: |-
            curl --location --request POST \
              'https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding' \
            --header "Authorization: Bearer $DASHSCOPE_API_KEY" \
            --header 'Content-Type: application/json' \
            --data '{
                "model": "tongyi-embedding-vision-plus",
                "input": {
                    "contents": [
                        {
                            "text": "Test text for generating a fused multimodal vector",
                            "image": "https://example.com/image.png",
                            "video": "https://example.com/video.mp4"
                        }
                    ]
                },
                "parameters": {
                    "dimension": 1024
                }
            }'
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
      description: 千问 AI 平台 API Key。详见[获取 API Key](/api-reference/preparation/api-key)。
  schemas:
    SyncImageRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 模型名称。文生图使用 `wan2.6-t2i`，图像编辑与图文交替输出使用 `wan2.6-image`，轻量快速生成使用 `z-image-turbo`。
          enum:
            - wan2.6-t2i
            - wan2.6-image
            - z-image-turbo
          example: wan2.6-t2i
        input:
          type: object
          required:
            - messages
          description: 包含消息数组的输入数据。
          properties:
            messages:
              type: array
              description: 仅支持单轮对话，包含一条角色为 `user` 的消息。
              minItems: 1
              maxItems: 1
              items:
                $ref: "#/components/schemas/ImageMessage"
        parameters:
          $ref: "#/components/schemas/SyncImageParameters"
    ImageMessage:
      type: object
      required:
        - role
        - content
      properties:
        role:
          type: string
          enum:
            - user
          description: 必须为 `user`。
        content:
          type: array
          description: 内容项数组，必须包含且仅包含一个文本对象。使用图像编辑模式（`wan2.6-image`）时，还可包含 1-4 个图像对象（编辑模式）或 0-1 个图像对象（图文交替模式）。
          items:
            $ref: "#/components/schemas/ImageContentPart"
    ImageContentPart:
      type: object
      description: 消息中的内容项。每个对象只能提供 `text` 或 `image` 其中之一，不可同时包含两者。
      properties:
        text:
          type: string
          description: 图像生成提示词。`wan2.6-t2i` 最多 2100 个字符，`wan2.6-image` 最多 2000 个字符，`z-image-turbo` 最多 800 个字符。每个内容数组中只允许包含一个文本对象。
          maxLength: 2100
        image:
          type: string
          description: 参考图像 URL（HTTP/HTTPS）或 Base64 数据 URI（`data:{MIME_type};base64,{data}`）。仅限图像编辑模式（`wan2.6-image` 且 `enable_interleave=false`）：需提供 1-4 张图像；图文交替模式：0-1 张图像。支持格式：JPEG、JPG、PNG、BMP、WEBP。分辨率：每边 [384, 5000] 像素，最大 10 MB。
    SyncImageParameters:
      type: object
      description: 生成参数。
      properties:
        size:
          type: string
          description: 输出分辨率，格式为 `宽*高`。`wan2.6-t2i`：总像素范围 [1280x1280, 1440x1440]，宽高比 [1:4, 4:1]，默认值：`1280*1280`。`wan2.6-image`：总像素范围 [768x768, 1280x1280]，宽高比 [1:4, 4:1]，默认值：`1280*1280`。`z-image-turbo`：总像素范围 [512x512, 2048x2048]，默认值：`1024*1536`。
          default: 1280*1280
          example: 1280*1280
        n:
          type: integer
          description: 生成图像数量，范围 1-4，默认值：4，按实际生成张数计费。图文交替模式下必须为 1。
          minimum: 1
          maximum: 4
          default: 4
        prompt_extend:
          type: boolean
          description: 开启智能提示词扩写，会增加约 3-4 秒延迟。适用于 `wan2.6-t2i`、`wan2.6-image`（仅编辑模式）及 `z-image-turbo`。`z-image-turbo` 开启后费用更高（详见定价）。wan2.6 系列默认值：`true`，z-image-turbo 默认值：`false`。
          default: true
        watermark:
          type: boolean
          description: 在输出图像上添加 "AI 生成" 水印，默认值：`false`。
          default: false
        negative_prompt:
          type: string
          description: 生成图像时需排除的元素，仅适用于 `wan2.6-t2i`。
        enable_interleave:
          type: boolean
          description: 仅适用于 `wan2.6-image`。`false`（默认）：图像编辑模式；`true`：图文交替输出模式（需开启流式输出）。
          default: false
        max_images:
          type: integer
          description: 仅适用于 `wan2.6-image` 图文交替模式，每次响应最多生成的图像数量，范围 1-5，默认值：5。实际数量由模型决定。
          minimum: 1
          maximum: 5
          default: 5
        stream:
          type: boolean
          description: 开启流式输出。图文交替模式（`enable_interleave=true`）时必须设置为 `true`，默认值：`false`。
          default: false
    AsyncImageRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 异步图像生成的模型名称。
          enum:
            - wan2.6-t2i
            - wan2.5-t2i-preview
            - wan2.2-t2i-flash
            - wan2.2-t2i-plus
            - wanx2.1-t2i-turbo
            - wanx2.1-t2i-plus
            - flux-schnell
            - flux-dev
            - flux-merged
          example: wan2.6-t2i
        input:
          type: object
          required:
            - messages
          description: 包含消息数组的输入数据。
          properties:
            messages:
              type: array
              description: 仅支持单轮对话，包含一条角色为 `user` 的消息。
              minItems: 1
              maxItems: 1
              items:
                $ref: "#/components/schemas/ImageMessage"
        parameters:
          $ref: "#/components/schemas/AsyncImageParameters"
    AsyncImageParameters:
      type: object
      description: 异步图像生成的生成参数。
      properties:
        size:
          type: string
          description: 输出分辨率，格式为 `宽*高`，支持的值因模型而异。Wan 系列：参见各模型限制；FLUX 系列：`512*1024`、`768*512`、`768*1024`、`1024*576`、`576*1024`、`1024*1024`。默认值：`1280*1280`（Wan）或 `1024*1024`（FLUX）。
          example: 1280*1280
        n:
          type: integer
          description: 生成图像数量，范围 1-4，默认值：4（Wan 系列）或 1（FLUX 系列）。
          minimum: 1
          maximum: 4
        prompt_extend:
          type: boolean
          description: 开启智能提示词扩写，会增加约 3-4 秒延迟，默认值：`true`。
          default: true
        watermark:
          type: boolean
          description: 在输出图像上添加 "AI 生成" 水印，默认值：`false`。
          default: false
        negative_prompt:
          type: string
          description: 生成图像时需排除的元素。
    SpecializedImageRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 专项图像任务的模型名称。
          enum:
            - wanx-style-repaint-v1
            - wanx-background-generation-v2
            - image-expansion
            - wanx-poster-generation-v1
            - image-inpainting
            - person-segmentation
            - wanx-sketch-to-image-v1
            - aitryon-v1
            - aitryon-v2
            - virtual-model
            - shoe-model
            - facechain-generation
          example: aitryon-v2
        input:
          type: object
          description: 特定于模型的输入数据，结构因模型而异。详见上方接口描述中各模型的参数说明。
          properties:
            person_image_url:
              type: string
              description: 人物图像 URL，适用于 `aitryon-v1` 和 `aitryon-v2`。
            garment_image_url:
              type: string
              description: 服装图像 URL，适用于 `aitryon-v1` 和 `aitryon-v2`。
            base_image_url:
              type: string
              description: 前景/产品图像 URL，适用于 `wanx-background-generation-v2`。
            prompt:
              type: string
              description: 描述期望输出效果的文本提示词，适用于 `wanx-background-generation-v2` 及其他模型。
        parameters:
          $ref: "#/components/schemas/SpecializedImageParameters"
    SpecializedImageParameters:
      type: object
      description: 专项图像任务的参数，可用参数因模型而异。
      properties:
        n:
          type: integer
          description: 生成图像数量，范围 1-4，默认值因模型而异。
          minimum: 1
          maximum: 4
        resolution:
          type: integer
          description: 输出分辨率（短边像素数），适用于虚拟试穿模型，默认值：768。
          default: 768
    WordArtRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 艺术字生成的模型名称。
          enum:
            - wordart-texture
            - wordart-deformation-v1
          example: wordart-texture
        input:
          type: object
          required:
            - text
            - prompt
          description: 艺术字生成的输入数据。
          properties:
            text:
              type: object
              required:
                - text_content
                - font_name
              description: 文字配置。
              properties:
                text_content:
                  type: string
                  description: 要渲染的文本内容，最多 6 个字符。
                  maxLength: 6
                  example: AI
                font_name:
                  type: string
                  description: 基础文字的字体名称。
                  example: dongfangdakai
            prompt:
              type: string
              description: 纹理效果的风格描述。
              example: Flames and fire, burning effect
        parameters:
          type: object
          description: 生成参数。
          properties:
            n:
              type: integer
              description: 生成图像数量，默认值：4。
              default: 4
    MultimodalEmbeddingRequest:
      type: object
      required:
        - model
        - input
      properties:
        model:
          type: string
          description: 多模态向量嵌入的模型名称。
          enum:
            - tongyi-embedding-vision-plus
            - tongyi-embedding-vision-flash
          example: tongyi-embedding-vision-plus
        input:
          type: object
          required:
            - contents
          description: 包含内容项的输入数据。
          properties:
            contents:
              type: array
              description: 内容项列表，每项为包含一个或多个模态键（`text`、`image`、`video`、`multi_images`）的对象。生成独立向量时每个对象只使用一种模态；生成融合向量时将多种模态组合在同一对象中。
              items:
                $ref: "#/components/schemas/MultimodalContentItem"
        parameters:
          $ref: "#/components/schemas/MultimodalEmbeddingParameters"
    MultimodalContentItem:
      type: object
      description: 多模态向量嵌入的内容项，可包含一个或多个模态键。生成独立向量时每个对象使用一个键；生成融合向量时在同一对象中组合多个键。
      properties:
        text:
          type: string
          description: 要嵌入的文本内容。
        image:
          type: string
          description: 图像 URL（公开的 HTTP/HTTPS 链接）或 Base64 数据 URI（`data:image/{format};base64,{data}`）。
        video:
          type: string
          description: 视频 URL（必须为公开链接）。
        multi_images:
          type: array
          description: 用于多图嵌入的图像 URL 列表，最多 8 张图像，仅 `tongyi-embedding-vision-plus` 和 `tongyi-embedding-vision-flash` 支持。
          items:
            type: string
          maxItems: 8
    MultimodalEmbeddingParameters:
      type: object
      description: 多模态向量嵌入的参数。
      properties:
        output_type:
          type: string
          description: 输出格式，目前仅支持 `dense`。
          enum:
            - dense
          default: dense
        dimension:
          type: integer
          description: 输出向量维度，支持的值因模型而异，详见模型概览表中的默认值与可选项。
        fps:
          type: number
          description: 视频帧采样率，范围 [0, 1]，默认值：1.0。
          minimum: 0
          maximum: 1
          default: 1
        instruct:
          type: string
          description: 自定义任务指令，建议使用英文，通常可使检索任务效果提升 1-5%。
    SyncImageResponse:
      type: object
      description: 同步图像生成或编辑的响应结果。
      properties:
        output:
          type: object
          properties:
            choices:
              type: array
              description: 生成结果列表。
              items:
                $ref: "#/components/schemas/ImageChoice"
            finished:
              type: boolean
              description: 任务是否已完成。
        usage:
          $ref: "#/components/schemas/ImageUsage"
        request_id:
          type: string
          description: 唯一请求标识符。
          example: 815505c6-7c3d-49d7-b197-xxxxx
    ImageChoice:
      type: object
      properties:
        finish_reason:
          type: string
          description: 正常完成时为 `stop`，流式输出过程中为 `null`。
          example: stop
        message:
          type: object
          properties:
            role:
              type: string
              description: 始终为 `assistant`。
              enum:
                - assistant
            content:
              type: array
              description: 内容项数组，每项包含图像 URL 或文本（图文交替模式下）。
              items:
                $ref: "#/components/schemas/ImageResponseContentPart"
    ImageResponseContentPart:
      type: object
      description: 响应消息中的内容项。
      properties:
        type:
          type: string
          description: 内容类型：`image` 或 `text`（仅图文交替模式下包含文本）。
          enum:
            - image
            - text
        image:
          type: string
          description: 生成的图像 URL（PNG 格式），**有效期 24 小时**，当 `type` 为 `image` 时存在。
        text:
          type: string
          description: 生成的文本内容，当 `type` 为 `text` 时存在（图文交替模式）。
    ImageUsage:
      type: object
      description: 图像生成的用量统计。
      properties:
        image_count:
          type: integer
          description: 已生成的图像数量。
        input_tokens:
          type: integer
          description: 消耗的输入 token 数，编辑模式下为 0，图文交替模式下为实际值。
        output_tokens:
          type: integer
          description: 消耗的输出 token 数，编辑模式下为 0，图文交替模式下为实际值。
        size:
          type: string
          description: 输出分辨率。
          example: 1280*1280
        total_tokens:
          type: integer
          description: 总 token 数（input_tokens + output_tokens）。
    AsyncTaskSubmitResponse:
      type: object
      description: 异步任务提交后的响应结果。
      properties:
        request_id:
          type: string
          description: 唯一请求标识符。
        output:
          type: object
          properties:
            task_id:
              type: string
              description: 用于轮询状态的任务 ID，配合 `GET /tasks/{task_id}` 使用。
            task_status:
              type: string
              description: 任务初始状态，通常为 `PENDING`。
              enum:
                - PENDING
                - RUNNING
                - SUCCEEDED
                - FAILED
    AsyncTaskStatusResponse:
      type: object
      description: 异步任务的状态与结果。
      properties:
        request_id:
          type: string
          description: 唯一请求标识符。
        output:
          type: object
          properties:
            task_id:
              type: string
              description: 任务 ID。
            task_status:
              type: string
              description: 当前任务状态。
              enum:
                - PENDING
                - RUNNING
                - SUCCEEDED
                - FAILED
            results:
              type: array
              description: 已生成的图像结果列表，当 `task_status` 为 `SUCCEEDED` 时存在。
              items:
                $ref: "#/components/schemas/AsyncTaskResult"
            task_metrics:
              $ref: "#/components/schemas/TaskMetrics"
        usage:
          type: object
          description: 用量统计。
          properties:
            image_count:
              type: integer
              description: 成功生成的图像数量。
    AsyncTaskResult:
      type: object
      description: 异步任务的单条结果。
      properties:
        url:
          type: string
          description: 生成图像的 URL，**有效期 24 小时**。
    TaskMetrics:
      type: object
      description: 任务完成情况统计。
      properties:
        TOTAL:
          type: integer
          description: 请求生成的图像总数。
        SUCCEEDED:
          type: integer
          description: 成功生成的图像数量。
        FAILED:
          type: integer
          description: 生成失败的图像数量。
    MultimodalEmbeddingResponse:
      type: object
      description: 多模态向量嵌入的响应结果。
      properties:
        output:
          type: object
          properties:
            embeddings:
              type: array
              description: 向量嵌入结果列表。
              items:
                $ref: "#/components/schemas/MultimodalEmbeddingData"
        usage:
          type: object
          description: Token 用量统计。不同模型返回的字段存在差异：`tongyi-embedding-vision-*` 系列返回 `input_tokens`（含文本和图片 Token 总和）、`input_tokens_details`、`output_tokens`、`total_tokens`；其他模型返回的字段可能不同，详见各字段说明。
          properties:
            input_tokens:
              type: integer
              description: 本次请求输入内容的 Token 数目。对于 `tongyi-embedding-vision-*` 系列模型，该值包含文本和图片/视频 Token 的总和。
            input_tokens_details:
              type: object
              description: 输入 Token 的详细分类信息。仅 `tongyi-embedding-vision-*` 系列模型返回此字段。
              properties:
                image_tokens:
                  type: integer
                  description: 输入内容中图片或视频等视觉部分消耗的 Token 数量，不包含文本（文本部分见 `text_tokens`）。图片消耗的 Token 数量与输入图片的分辨率有关，分辨率越高消耗的 Token 越多；若输入为视频，系统会先对视频抽帧，再基于抽帧结果计算 Token。
                text_tokens:
                  type: integer
                  description: 输入内容中文本部分消耗的 Token 数量（不包含图片或视频等视觉部分）。
            output_tokens:
              type: integer
              description: 本次请求输出的 Token 数目。仅 `tongyi-embedding-vision-*` 系列模型返回此字段。
            total_tokens:
              type: integer
              description: 输入与输出的 Token 总数。
            image_tokens:
              type: integer
              description: 本次请求输入的图片或视频等视觉部分消耗的 Token 数量（不包含文本）。图片消耗的 Token 数量与输入图片的分辨率有关；系统会对输入视频进行抽帧处理，帧数上限受系统配置控制，随后基于处理结果计算 Token。仅 `qwen3-vl-embedding`、`qwen2.5-vl-embedding` 和 `multimodal-embedding-v1` 返回此字段（作为顶层字段），`tongyi-embedding-vision-*` 系列模型的图片 Token 包含在 `input_tokens_details.image_tokens` 中。
        request_id:
          type: string
          description: 唯一请求标识符。
          example: 1fff9502-a6c5-9472-9ee1-73930fdd04c5
    MultimodalEmbeddingData:
      type: object
      description: 单条向量嵌入结果。
      properties:
        index:
          type: integer
          description: 在输入内容列表中的位置索引。
        embedding:
          type: array
          description: 浮点数向量。
          items:
            type: number
        type:
          type: string
          description: 本条嵌入结果的内容类型。
          enum:
            - text
            - image
            - video
    DashScopeErrorResponse:
      type: object
      description: DashScope API 错误响应。
      properties:
        request_id:
          type: string
          description: 唯一请求标识符。
        code:
          type: string
          description: 错误码（如 `InvalidParameter`、`Throttling`、`Unauthorized`）。
          example: InvalidParameter
        message:
          type: string
          description: 可读的错误信息。
          example: num_images_per_prompt must be 1
````