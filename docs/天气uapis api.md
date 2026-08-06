````
---
title: "查询天气"
locale: zh-CN
canonical: https://uapis.cn/docs/api-reference/get-misc-weather
source: https://uapis.cn/docs/api-reference/get-misc-weather.md
---

# 查询天气

**分类：** 杂项

出门前，查一下天气总是个好习惯。这个接口为你提供精准、实时的天气数据，支持国内和国际城市。

## 功能概述
这个接口支持三种查询方式：
- 可以传 `adcode`，按行政区编码查询（优先级最高）
- 可以传 `city`，按城市名称查询，支持中文（`北京`）和英文（`Tokyo`）
- 两个都不传时，按客户端 IP 自动定位查询

支持 `lang` 参数，可选 `zh`（默认）和 `en`，城市名翻译覆盖 7000+ 城市。

## 可选功能模块
- `extended=true`：扩展气象字段（体感温度、能见度、气压、紫外线、空气质量及污染物分项数据）
- `forecast=true`：多天预报（最多7天，会额外返回每天的最高温度、最低温度，以及日出日落、风速等详细数据）
- `hourly=true`：逐小时预报（24小时）
- `minutely=true`：分钟级降水预报（仅国内城市，精确到2分钟）
- `indices=true`：18项生活指数（穿衣、紫外线、洗车、运动、花粉等）

## 天气字段说明
`weather` 是天气现象文本，不是固定枚举。

常见值包括：晴、多云、阴、小雨、中雨、大雨、雷阵雨、小雪、中雪、大雪、雨夹雪、雾、霾、沙尘。

如果你的业务需要稳定的天气分类，建议使用 `weather_code` 进行映射。完整的天气图标代码请参考[天气图标代码表](#enum-list)。

## API 端点

**方法：** GET
**路径：** /misc/weather
**完整API地址：** https://uapis.cn/api/v1/misc/weather
**文档页面：** https://uapis.cn/docs/api-reference/get-misc-weather

## 响应

### 200 / 请求成功

查询成功！返回该地区的实时天气信息。

```json
{
  // 省份
  "province": "北京市",
  // 城市名
  "city": "北京",
  // 区县或更细一级的行政区名称。自动按 IP 定位时更常见。
  "district": "海淀区",
  // 行政区划代码（部分数据源可能为空）
  "adcode": "",
  // 天气状况描述。默认返回中文，传 `lang=en` 时返回英文。非固定枚举。
  "weather": "晴",
  // 天气图标代码。请从[天气图标代码表](#enum-list)中查看所有可能的值。
  "weather_icon": "100",
  // 当前温度 °C
  "temperature": 18.3,
  // 风向
  "wind_direction": "西南风",
  // 风力等级
  "wind_power": "微风",
  // 相对湿度 %
  "humidity": 20,
  // 数据更新时间
  "report_time": "2026-02-19 15:25:58",
  // 体感温度 °C（extended=true 时返回）
  "feels_like": 6,
  // 能见度 km（extended=true 时返回）
  "visibility": 11.3,
  // 气压 hPa（extended=true 时返回）
  "pressure": 1017.5,
  // 紫外线指数（extended=true 时返回）
  "uv": 2.9,
  // 当前降水量 mm（extended=true 时返回）
  "precipitation": 0,
  // 云量 %（extended=true 时返回）
  "cloud": 75,
  // 空气质量指数 0-500（extended=true 时返回）
  "aqi": 56,
  // AQI 等级 1-6（extended=true 时返回）
  "aqi_level": 2,
  // AQI 等级描述（优/良/轻度污染/中度污染/重度污染/严重污染）（extended=true 时返回）
  "aqi_category": "良",
  // 主要污染物（如 PM2.5、PM10、O3 等）（extended=true 时返回）
  "aqi_primary": "PM10",
  // 空气污染物分项数据（extended=true 时返回，部分数据源可能不返回）
  "air_pollutants": {
    // PM2.5 μg/m³
    "pm25": 33,
    // PM10 μg/m³
    "pm10": 69,
    // 臭氧 μg/m³
    "o3": 91,
    // 二氧化氮 μg/m³
    "no2": 13,
    // 二氧化硫 μg/m³
    "so2": 7,
    // 一氧化碳 mg/m³
    "co": 0.4
  },
  // 官方气象预警列表（存在有效预警时返回）
  "alerts": [
    {
      // 预警标题
      "title": "string",
      // 预警类型，如雷电、暴雨
      "type": "string",
      // 预警级别，如蓝色、黄色、橙色、红色
      "level": "string",
      // 预警正文
      "text": "string",
      // 预警发布时间
      "publish_time": "string",
      // 发布单位
      "publisher": "string",
      // 防御指引列表
      "guidance": [
        "string"
      ]
    }
  ],
  // 当天最高温 °C（forecast=true 时返回）
  "temp_max": 14,
  // 当天最低温 °C（forecast=true 时返回）
  "temp_min": -1,
  // 多天天气预报，最多7天（forecast=true 时返回）
  "forecast": [
    {
      // 日期 YYYY-MM-DD
      "date": "2026-02-19",
      // 星期几（`lang=en` 时返回英文星期）
      "week": "星期四",
      // 最高温度 °C
      "temp_max": 14,
      // 最低温度 °C
      "temp_min": -1,
      // 白天天气（`lang=en` 时返回英文）
      "weather_day": "晴",
      // 夜间天气（`lang=en` 时返回英文）
      "weather_night": "晴",
      // 白天风向（可选，`lang=en` 时返回英文）
      "wind_dir_day": "西南风",
      // 夜间风向（可选，`lang=en` 时返回英文）
      "wind_dir_night": "北风",
      // 白天风力（可选，`lang=en` 时返回英文）
      "wind_scale_day": "微风",
      // 夜间风力（可选，`lang=en` 时返回英文）
      "wind_scale_night": "微风",
      // 白天风速 km/h（可选）
      "wind_speed_day": 17,
      // 湿度 %（可选）
      "humidity": 40,
      // 降水量 mm（可选）
      "precip": 0,
      // 能见度 km（可选）
      "visibility": 25,
      // 紫外线指数（可选）
      "uv_index": 5,
      // 日出时间 HH:MM（可选）
      "sunrise": "06:52",
      // 日落时间 HH:MM（可选）
      "sunset": "17:56"
    }
  ],
  // 逐小时预报，最多24小时（hourly=true 时返回）
  "hourly_forecast": [
    {
      // 预报时间（ISO8601 或 YYYY-MM-DD HH:MM）
      "time": "2026-02-19T17:00:00+0900",
      // 温度 °C
      "temperature": 8,
      // 天气状况
      "weather": "晴",
      // 风向（可选）
      "wind_direction": "北北西",
      // 风速 km/h（可选）
      "wind_speed": 17,
      // 风力等级（可选）
      "wind_scale": "3级",
      // 湿度 %（可选）
      "humidity": 25,
      // 降水量 mm（可选）
      "precip": 0,
      // 体感温度 °C（可选）
      "feels_like": 6,
      // 能见度 km（可选）
      "visibility": 14,
      // 降水概率 %（可选）
      "pop": 0,
      // 紫外线指数（可选，国内城市通常不返回）
      "uv_index": 0
    }
  ],
  // 分钟级降水预报（minutely=true 时返回，仅国内城市可用，精确到2分钟）
  "minutely_precip": {
    // 降水描述
    "summary": "未来2小时无降水",
    // 更新时间
    "update_time": "2026-02-19T15:30:00+08:00",
    // 精确到2分钟的数据点
    "data": [
      {
        // 预报时间 ISO8601
        "time": "2026-02-19T15:30:00+08:00",
        // 该时间点的降水量 mm
        "precip": 0,
        // 降水类型：rain / snow
        "type": "rain"
      }
    ]
  },
  // 18项生活指数（indices=true 时返回），每项包含 level（等级名称）、brief（简短描述）、advice（详细建议）
  "life_indices": {
    // 穿衣指数
    "clothing": {
      "level": "较舒适",
      "brief": "微凉",
      "advice": "建议穿薄外套、卫衣或长袖衬衫"
    },
    // 紫外线指数
    "uv": {
      "level": "高",
      "brief": "较强",
      "advice": "紫外线较强，减少10-14点户外活动，涂抹SPF30+防晒霜，戴帽子和墨镜"
    },
    // 洗车指数
    "car_wash": {
      "level": "非常适宜",
      "brief": "极佳",
      "advice": "天气晴好，非常适合洗车"
    },
    // 晾晒指数
    "drying": {
      "level": "适宜",
      "brief": "较好",
      "advice": "天气较好，适合晾晒"
    },
    // 空调开启指数
    "air_conditioner": {
      "level": "建议制热",
      "brief": "寒冷",
      "advice": "建议开启空调制热"
    },
    // 感冒指数
    "cold_risk": {
      "level": "较低",
      "brief": "较少发",
      "advice": "感冒风险较低"
    },
    // 运动指数
    "exercise": {
      "level": "适宜",
      "brief": "较好",
      "advice": "天气适合运动"
    },
    // 舒适度指数
    "comfort": {
      "level": "冷",
      "brief": "偏冷",
      "advice": "体感偏冷，适当添加衣物"
    },
    // 出行指数
    "travel": {
      "level": "适宜",
      "brief": "较好",
      "advice": "天气较好，适合出行"
    },
    // 钓鱼指数
    "fishing": {
      "level": "适宜",
      "brief": "较好",
      "advice": "天气适合钓鱼"
    },
    // 过敏指数
    "allergy": {
      "level": "较低",
      "brief": "不易发",
      "advice": "过敏风险较低"
    },
    // 防晒指数
    "sunscreen": {
      "level": "中等",
      "brief": "需防晒",
      "advice": "建议涂抹防晒霜"
    },
    // 心情指数
    "mood": {
      "level": "较好",
      "brief": "愉悦",
      "advice": "天气不错，心情愉悦"
    },
    // 啤酒指数
    "beer": {
      "level": "适宜",
      "brief": "较好",
      "advice": "适合来一杯冰啤酒"
    },
    // 雨伞指数
    "umbrella": {
      "level": "不需要",
      "brief": "无需",
      "advice": "天气晴好，无需带伞"
    },
    // 交通指数
    "traffic": {
      "level": "良好",
      "brief": "较好",
      "advice": "天气对交通无明显影响"
    },
    // 空气净化器指数
    "air_purifier": {
      "level": "建议开启",
      "brief": "一般",
      "advice": "空气质量一般，建议开启空气净化器"
    },
    // 花粉扩散指数
    "pollen": {
      "level": "较低",
      "brief": "不易发",
      "advice": "花粉浓度较低"
    }
  }
}
```

### 400 / 错误的请求

参数无效。常见原因：`adcode` 格式非法、`lang` 非法（仅支持 zh/en）、参数值类型错误或参数组合无效。

```json
{
  "code": "INVALID_PARAMETER",
  "message": "参数无效"
}
```

### 404 / 未找到

城市未找到。

```json
{
  "code": "NOT_FOUND",
  "message": "未找到该城市的天气数据"
}
```

### 500 / 服务器内部错误

服务器内部错误。

```json
{
  "code": "INTERNAL_SERVER_ERROR",
  "message": "服务器内部错误"
}
```

### 503 / 服务不可用

天气服务暂时不可用。

```json
{
  "code": "SERVICE_UNAVAILABLE",
  "message": "天气服务暂时不可用"
}
```

## 查询参数

- **`city`** (string)
  城市名称，支持中文（`北京`）和英文（`Tokyo`）。可选参数，不传时会尝试 IP 自动定位。
  示例：`北京`
  提示：与 adcode 至少传一个，或都不传走自动定位。

- **`adcode`** (string)
  城市行政区划代码（如 `110000`），优先级高于 city。可选参数，不传时会尝试 IP 自动定位。
  提示：传 adcode 时优先按 adcode 查询。

- **`extended`** (boolean)
  返回扩展气象字段（体感温度、能见度、气压、紫外线、降水量、云量、空气质量指数及污染物分项数据）。
  可选值：`false`、`true`
  提示：设为 true 获取更多气象数据

- **`forecast`** (boolean)
  返回多天预报数据（最多7天），含每天的最高温度、最低温度、白天夜间天气、风向风力、日出日落等。
  可选值：`false`、`true`
  提示：设为 true 获取最多 7 天预报，并返回每天的最高温度和最低温度

- **`hourly`** (boolean)
  返回逐小时预报（24小时），含温度、天气、风向风速、湿度、降水概率等。
  可选值：`false`、`true`
  提示：设为 true 获取逐小时预报

- **`minutely`** (boolean)
  返回分钟级降水预报（仅国内城市），精确到2分钟。
  可选值：`false`、`true`
  提示：仅国内城市可用，设为 true 获取精确到2分钟的分钟级降水

- **`indices`** (boolean)
  返回18项生活指数（穿衣、紫外线、洗车、晾晒、空调、感冒、运动、舒适度、出行、钓鱼、过敏、防晒、心情、啤酒、雨伞、交通、空气净化器、花粉）。
  可选值：`false`、`true`
  提示：设为 true 获取18项生活建议指数

- **`lang`** (string)
  返回语言。`zh` 返回中文（默认），`en` 返回英文。城市名翻译覆盖 7000+ 城市。生活指数（`indices`）目前仅支持中文。
  可选值：`zh`、`en`
  默认值：`zh`
  提示：国际化场景建议传 en。
````