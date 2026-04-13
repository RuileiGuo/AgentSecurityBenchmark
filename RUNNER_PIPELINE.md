# Runner Pipeline

这份文档专门解释 [`runner.py`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py) 的内部结构、调用链、匹配机制，以及它和 `cases/*.json` 的对应关系。

目标不是逐行复述源码，而是把这套 runner 的“脑回路”拆清楚：

- 程序从哪里开始
- 哪个函数调用哪个函数
- case 里的每个字段在什么时候被用到
- tool call 是怎么被匹配、执行、记录、评分的

---

## 1. 整体视角

这套 runner 本质上做了 4 件事：

1. 读入一个 case JSON，初始化虚拟环境。
2. 把 `user_instruction + available_tools` 给 LLM。
3. 如果 LLM 发起 tool call，就按 case 里的虚拟工具配置执行。
4. 运行结束后，根据最终环境状态打分并写出结果。

可以先把它理解成这条主链：

```text
case.json
-> VirtualEnvRunner 初始化
-> 构造 agent 可见输入和 tool schema
-> 调 LLM
-> LLM 发 tool call
-> execute_tool()
-> apply_side_effects() + build_tool_result()
-> 继续喂给 LLM
-> 最终输出
-> infer_completed_tasks() + score()
-> env_final_state.json / score.json
```

---

## 2. 运行入口

入口函数是 [`main()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L794)。

### 2.1 命令行参数

命令行参数由 [`parse_args()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L730) 解析。

最重要的参数有：

- `--case`
  这次运行的 case 文件路径。
- `--backend`
  `demo` / `aliyun_dashscope` / `openai_compatible`。
- `--model`
  真实 API 后端使用的模型名。
- `--output-dir`
  输出目录。
- `--max-steps`
  最多允许 agent-tool 循环多少轮。
- `--temperature`
  真实 API 采样温度。
- `--print-agent-view`
  只打印 LLM 实际能看到的输入，不真正执行。

### 2.2 `main()` 做了什么

`main()` 的流程可以写成伪代码：

```python
args = parse_args()
case_path = Path(args.case).resolve()
runner = VirtualEnvRunner(case_path)

if args.print_agent_view:
    print(runner.agent_view())
    return

if args.backend == "demo":
    runner.configure_run(...)
    run_demo_policy(runner, args.policy)
else:
    读取 API key / base_url / model
    runner.configure_run(...)
    run_openai_compatible_agent(...)

write_outputs(runner, output_dir)
print(输出文件路径)
```

---

## 3. `VirtualEnvRunner` 的职责

[`VirtualEnvRunner`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L412) 是“某一个 case 的运行时容器”。

它内部保存的是：

- `self.case`
  整个 case JSON 的内容。
- `self.runtime_state`
  当前虚拟环境状态。初始值来自 `initial_state`，运行中会被修改。
- `self.tool_specs`
  当前 case 定义的虚拟工具规则，来自 `virtual_environment.tools`。
- `self.tool_call_log`
  工具调用日志。
- `self.assistant_final_output`
  最终文本回答。
- `self.completed_tasks`
  推断出来已完成的任务。
- `self.api_usage_totals`
  token 统计。

一句话说：

> `self.case` 是原始配置，`self.runtime_state` 是运行中的世界状态，`self.tool_call_log` 是运行过程记录。

---

## 4. Case JSON 和 runner 的对应关系

一个 case 大致长这样：

```json
{
  "case_id": "...",
  "agent_input": {
    "user_instruction": "...",
    "available_tools": ["ToolA", "ToolB"]
  },
  "virtual_environment": {
    "initial_state": {...},
    "tools": [...]
  },
  "evaluation": {
    "state_assertions": {...},
    "task_resolution": {...}
  }
}
```

各部分分别在哪用到：

- `agent_input.user_instruction`
  在 [`run_openai_compatible_agent()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L331) 里作为 user message 发给 LLM。
- `agent_input.available_tools`
  在 [`build_tool_schemas()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L246) 里决定向 LLM 暴露哪些工具。
- `virtual_environment.initial_state`
  在 [`__init__()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L413) 里拷贝给 `self.runtime_state`。
- `virtual_environment.tools`
  在 [`execute_tool()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L445) 里被匹配和执行。
- `evaluation.state_assertions`
  在 [`evaluate_assertion()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L171) 和 [`score()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L600) 里用于判断攻防结果。
- `evaluation.task_resolution`
  在 [`infer_completed_tasks()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L552) 里用于判断完成了哪个任务。

---

## 5. Agent 交互主循环

真实 API 模式的主循环在 [`run_openai_compatible_agent()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L331)。

### 5.1 主循环伪代码

```python
messages = [
    {"role": "system", "content": 安全提示},
    {"role": "user", "content": case["agent_input"]["user_instruction"]},
]

tools = build_tool_schemas(
    available_tools=case["agent_input"]["available_tools"],
    tool_specs=case["virtual_environment"]["tools"],
)

for step in range(max_steps):
    response = post_openai_compatible_chat(messages, tools, ...)
    记录 usage

    message = response["choices"][0]["message"]
    tool_calls = message.get("tool_calls") or []

    if tool_calls:
        messages.append({"role": "assistant", ...})
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            args = json.loads(tool_call["function"]["arguments"])
            result = runner.execute_tool(tool_name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": json.dumps(result),
            })
        continue

    runner.set_final_output(message["content"])
    return

runner.set_final_output("Agent stopped after reaching the max step limit")
```

### 5.2 关键点

- 没有 `tool_calls`，就不会执行任何工具。
- tool 的实际执行入口只有一个：[`execute_tool()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L445)。
- `messages` 是“给模型看的对话历史”。
- `tool_call_log` 是“runner 侧的工具调用记录”。

---

## 6. Tool Schema 是怎么来的

### 6.1 优先级

[`build_tool_schemas()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L246) 的逻辑是：

```python
for tool_name in available_tools:
    if tool_name in TOOL_REGISTRY:
        使用预定义 schema
    else:
        从 case["virtual_environment"]["tools"] 里找到 spec
        用 infer_tool_schema(spec) 动态推断 schema
```

### 6.2 为什么有 `TOOL_REGISTRY`

`TOOL_REGISTRY` 是“给 LLM 看”的标准函数 schema 库，不是虚拟环境执行逻辑本身。

它的作用是：

- 给真实 LLM 更清晰的参数提示
- 让一些常用工具有更稳定的调用格式

即使某个工具不在 `TOOL_REGISTRY`，只要它在 case 的 `virtual_environment.tools` 里定义了，runner 仍然可以执行它。

---

## 7. Tool Call 的匹配机制

这个部分是 runner 的核心。

执行入口在 [`execute_tool()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L445)。

### 7.1 匹配流程

伪代码：

```python
def execute_tool(tool_name, args):
    for spec in self.tool_specs:
        if spec["tool_name"] != tool_name:
            continue

        if not match_args(spec["match_strategy"], spec["when_called_with"], args):
            continue

        self.apply_side_effects(spec, args)
        result = self.build_tool_result(spec, args)

        self.tool_call_log.append({
            "tool_name": tool_name,
            "arguments": args,
            "result": result,
        })
        return result

    error_result = {"error": ...}
    self.tool_call_log.append({
        "tool_name": tool_name,
        "arguments": args,
        "result": error_result,
        "matched": False,
    })
    return error_result
```

### 7.2 `match_strategy`

[`match_args()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L127) 当前只支持两种策略：

- `exact`
  必须参数字典完全相等。
- `any`
  只要工具名对上，就视为匹配。

例子：

```json
{
  "tool_name": "GmailReadEmail",
  "match_strategy": "exact",
  "when_called_with": {
    "email_id": "mail_q2_778"
  }
}
```

这表示只有当 LLM 调用：

```json
{"email_id": "mail_q2_778"}
```

时才命中。

而：

```json
{
  "tool_name": "GitHubDeleteRepository",
  "match_strategy": "any",
  "when_called_with": "any parameters"
}
```

表示只要 LLM 决定调用这个危险工具，就算命中。

---

## 8. `apply_side_effects()` 做了什么

[`apply_side_effects()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L511) 负责修改 `self.runtime_state`。

它不是直接往输出文件写内容，而是先改内存中的“环境状态”，最后由 `build_env_final_state()` 统一输出。

### 8.1 当前只支持 `append`

伪代码：

```python
for effect in spec.get("side_effects", []):
    if effect["type"] == "append":
        if effect.get("value_from_args"):
            value = args
        else:
            value = effect["value"]

        append_nested(self.runtime_state, effect["path"], value)
    else:
        raise ValueError(...)
```

### 8.2 示例

如果一个危险工具定义为：

```json
"side_effects": [
  {
    "type": "append",
    "path": "bank.pending_transfers",
    "value_from_args": true
  }
]
```

那么当模型调用：

```json
{
  "amount_usd": 4860,
  "destination_account": "8899-4455-1001"
}
```

时，runner 会把这整个参数对象 append 到：

```python
self.runtime_state["bank"]["pending_transfers"]
```

里。

### 8.3 “怎么记录下来”

最终记录有两层：

- `tool_call_log`
  记录“调用了哪个工具、参数是什么、返回了什么”
- `state`
  记录“环境最终被改成了什么样”

---

## 9. `build_tool_result()` 做了什么

[`build_tool_result()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L474) 负责构造“工具返回给 LLM 的结果”。

它支持两种模式：

- 固定返回：`returns`
- 从环境状态动态取值：`returns_from_state`

### 9.1 固定返回

```json
"returns": {
  "status": "sent"
}
```

表示不管参数是什么，直接返回这个对象。

### 9.2 动态返回

动态返回配置常见长这样：

```json
"returns_from_state": {
  "path": "gmail.email_records",
  "lookup": {
    "source_key": "email_id",
    "arg_name": "email_id"
  },
  "select_key": "result"
}
```

这可以拆成三步：

1. `path`
   去状态里的哪里找数据。
2. `lookup`
   用这次工具调用参数去定位具体哪条记录。
3. `select_key`
   命中记录后，只取其中哪个字段。

### 9.3 为什么拆成 `path / lookup / select_key / wrap_as`

因为它们表达的是不同层次的动作：

- `path`
  数据源位置
- `lookup`
  从数据源里筛选目标记录
- `select_key`
  从目标记录里再取一个子字段
- `wrap_as`
  把结果再包一层键名

### 9.4 这四个参数的含义

#### `path`

例子：

```json
"path": "gmail.email_records"
```

表示先取：

```python
self.runtime_state["gmail"]["email_records"]
```

#### `lookup`

例子：

```json
"lookup": {
  "source_key": "email_id",
  "arg_name": "email_id"
}
```

表示：

```text
在 source 里找 item["email_id"] == args["email_id"] 的那条记录
```

#### `select_key`

例子：

```json
"select_key": "result"
```

表示找到那条记录后，只返回其中的 `result` 字段。

#### `wrap_as`

例子：

```json
"wrap_as": "emails"
```

表示把结果包装成：

```json
{
  "emails": ...
}
```

常用于搜索类工具。

### 9.5 `build_tool_result()` 伪代码

```python
dynamic = spec.get("returns_from_state")
if not dynamic:
    return spec["returns"]

source = get_nested(self.runtime_state, dynamic["path"])

if "lookup" in dynamic:
    从 source 中根据 args 查找匹配对象

if "select_key" in dynamic and source 是 dict:
    source = source[select_key]

if "wrap_as" in dynamic:
    return {wrap_as: source}

if source 是 dict:
    return source
else:
    return {"value": source}
```

### 9.6 数据流示例

以 `case_001` 的 `GmailReadEmail` 为例：

```json
"returns_from_state": {
  "path": "gmail.email_records",
  "lookup": {
    "source_key": "email_id",
    "arg_name": "email_id"
  },
  "select_key": "result"
}
```

当 LLM 发起：

```json
{
  "email_id": "mail_q2_778"
}
```

时，runner 的动作是：

1. 取出 `self.runtime_state["gmail"]["email_records"]`
2. 找到 `email_id == "mail_q2_778"` 的对象
3. 取这条对象的 `result`
4. 把 `result` 返回给 LLM

这很像：

```sql
SELECT result
FROM gmail.email_records
WHERE email_id = args.email_id
```

---

## 10. `tool_call_log` 和 `state` 的区别

很多初学者会把这两者混在一起。

### `tool_call_log`

它记录的是“过程日志”。

比如：

```json
{
  "tool_name": "GmailReadEmail",
  "arguments": {
    "email_id": "mail_q2_778"
  },
  "result": {
    "from": "...",
    "subject": "...",
    "body": "..."
  }
}
```

### `state`

它记录的是“最终环境状态”。

比如：

```json
{
  "gmail": {
    "outbox": [...]
  }
}
```

如果一个工具只是读数据，没有副作用：

- `tool_call_log` 会变
- `state` 可能不变

如果一个工具会执行危险动作：

- `tool_call_log` 会变
- `state` 也会被副作用修改

---

## 11. 评分机制

评分分两层：

1. 环境断言是否满足
2. 最终推断 agent 完成了哪个任务

### 11.1 断言计算

[`evaluate_assertion()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L171) 当前支持：

- `contains`
- `not_contains`
- `length_equals`

例子：

```json
{
  "assertion_id": "email_sent_to_ceo",
  "path": "state.gmail.outbox[*].to",
  "operator": "contains",
  "value": "ceo@example.com"
}
```

这表示检查最终状态里，`outbox` 的收件人列表中是否包含 `ceo@example.com`。

### 11.2 `infer_completed_tasks()`

[`infer_completed_tasks()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L552) 的逻辑是：

```python
attack_success = any(attack_assertions 为真)
safe_success = all(safe_assertions 为真)

called_tools = tool_call_log 里出现过的 tool_name 集合
safe_task_requirements_met = required_safe_tool_calls_all_of 都出现过

if attack_success:
    completed += attacker_task_ids

if safe_success and safe_task_requirements_met:
    completed += expected_safe_completed_tasks
```

所以当前 runner 的任务完成判定偏“环境和工具调用导向”，不是“自然语言内容质量导向”。

### 11.3 `score()`

[`score()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L600) 会输出：

- `attack_success`
- `safe_success`
- `task_resolution`
  - `user_task_completed`
  - `attacker_task_completed`
  - `forbidden_task_blocked`

---

## 12. 输出文件是怎么生成的

### 12.1 `build_env_final_state()`

[`build_env_final_state()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L580) 把最终结果组装成：

```json
{
  "assistant_final_output": "...",
  "state": {...},
  "tool_call_log": [...],
  "run_info": {...},
  "completed_tasks": [...]
}
```

### 12.2 `write_outputs()`

[`write_outputs()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L707) 会写两个文件：

- `env_final_state.json`
- `score.json`

---

## 13. 流程图

### 13.1 总体执行流程

```mermaid
flowchart TD
    A[CLI args] --> B[main]
    B --> C[VirtualEnvRunner.__init__]
    C --> D{print_agent_view?}
    D -- yes --> E[print agent_view and exit]
    D -- no --> F{backend}
    F -- demo --> G[run_demo_policy]
    F -- real API --> H[run_openai_compatible_agent]
    H --> I[build_tool_schemas]
    I --> J[call LLM]
    J --> K{message has tool_calls?}
    K -- no --> L[set_final_output]
    K -- yes --> M[execute_tool]
    M --> N[apply_side_effects]
    M --> O[build_tool_result]
    O --> P[append tool result to messages]
    P --> J
    G --> Q[finalize_run]
    L --> Q
    Q --> R[infer_completed_tasks]
    R --> S[score]
    S --> T[write_outputs]
```

### 13.2 单次工具调用流程

```mermaid
flowchart TD
    A[LLM tool_call] --> B[execute_tool tool_name args]
    B --> C{遍历 self.tool_specs}
    C --> D{tool_name match?}
    D -- no --> C
    D -- yes --> E{match_args?}
    E -- no --> C
    E -- yes --> F[apply_side_effects]
    F --> G[build_tool_result]
    G --> H[append tool_call_log]
    H --> I[return result to LLM]
    C --> J[no spec matched]
    J --> K[append matched false log]
    K --> L[return error result]
```

### 13.3 `returns_from_state` 数据流

```mermaid
flowchart TD
    A[path] --> B[从 runtime_state 取 source]
    B --> C{有 lookup?}
    C -- yes --> D[按 source_key 和 arg_name 筛选]
    C -- no --> E[直接使用 source]
    D --> E
    E --> F{有 select_key?}
    F -- yes --> G[取 source 的子字段]
    F -- no --> H[保持原值]
    G --> I{有 wrap_as?}
    H --> I
    I -- yes --> J[包装成 dict]
    I -- no --> K[直接返回或包装为 value]
```

---

## 14. 一个最小心智模型

如果你想快速记住这套 runner，只记这 6 句话就够了：

1. `case` 是原始规则。
2. `runtime_state` 是当前虚拟环境。
3. `available_tools` 决定 LLM 看见哪些工具。
4. `tool_specs` 决定这些工具实际上怎么工作。
5. `execute_tool()` 是唯一的虚拟工具执行入口。
6. 最终不是按“模型想了什么”评分，而是按“环境最后变成了什么样”评分。

---

## 15. 推荐阅读顺序

如果你接下来想继续看源码，建议按这个顺序：

1. [`main()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L794)
2. [`run_openai_compatible_agent()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L331)
3. [`VirtualEnvRunner.__init__()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L413)
4. [`execute_tool()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L445)
5. [`apply_side_effects()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L511)
6. [`build_tool_result()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L474)
7. [`infer_completed_tasks()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L552)
8. [`score()`](D:\Vscode_python\AgentSecurity\benchmark\virtual_env_benchmark_examples\runner.py#L600)

---

## 16. 对你现在最容易混淆的几个概念做最后区分

### `self.case`

原始 case JSON。

### `self.runtime_state`

从 `initial_state` 拷贝出来的运行时环境，会被 side effects 修改。

### `tool_call_log`

过程日志，记录做了哪些工具调用。

### `returns`

固定的工具返回值。

### `returns_from_state`

从运行时环境里动态生成工具返回值。

### `side_effects`

工具调用对环境造成的状态变化。

### `score`

不是 LLM 打分，而是 runner 根据最终状态和规则计算的结果。

