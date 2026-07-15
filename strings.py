# 无理由判断list
_no_reason = ["无理由", "None", "NULL"]


def noreason_to_none(reason: str | None) -> str | None:
    if reason in _no_reason:
        return None
    return reason


def command_error(command: str) -> str:
    return messages["command_error"].format(
        command=command, commands_text=commands[command]
    )


def reason_format(reason: str | None) -> str:
    if noreason_to_none(reason):
        return reason
    else:
        return messages["no_reason"]


# command语法
commands = {
    "ban": "/ban <@用户|UID（QQ号）> [时间（默认无期限）] [理由（默认无理由）] [UMO]",
    "ban-all": "/ban-all <@用户|UID（QQ号）> [时间（默认无期限）] [理由（默认无理由）]",
    "pass": "/pass <@用户|UID（QQ号）> [时间（默认无期限）] [理由（默认无理由）] [UMO]",
    "pass-all": "/pass-all <@用户|UID（QQ号）> [时间（默认无期限）] [理由（默认无理由）]",
    "ban-enable": "/ban-enable",
    "ban-disable": "/ban-disable",
    "banlist": "/banlist",
    "ban-help": "/ban-help",
    "dec-ban": "/dec-ban <@用户|UID（QQ号）> [时间（默认无期限）] [理由（默认无理由）] [UMO]",
    "dec-pass": "/dec-pass <@用户|UID（QQ号）> [时间（默认无期限）] [理由（默认无理由）] [UMO]",
    "dec-ban-all": "/dec-ban-all <@用户|UID（QQ号）> [时间（默认无期限）] [理由（默认无理由）]",
    "dec-pass-all": "/dec-pass-all <@用户|UID（QQ号）> [时间（默认无期限）] [理由（默认无理由）]",
    "ban-reset": "/ban-reset <@用户|UID（QQ号）>",
    "random-ban": "/random-ban <@用户|UID（QQ号）> [UMO]",
    "silence-counter": "/silence-counter",
}

# 默认输出文案
messages = {
    "command_error": "语法错误，{command} 的语法应为 {commands_text}",
    "invalid_timestr_error": "时间字符串 {timestr} 格式错误，请使用数字+单位，如：1d3m51s",
    "time_zeroset_error": "相应的 {command} 记录已被设置为永久时限，不支持叠加操作",
    "banned_user": "已在 {umo} 禁用以下用户 {user}，时限：{time}，理由：{reason}",
    "banned_user_global": "已全局禁用 {user}，时限：{time}，理由：{reason}",
    "passed_user": "已在 {umo} 临时解限 {user}，时限：{time}，理由：{reason}",
    "passed_user_global": "已在全局临时解限 {user}，时限：{time}，理由：{reason}",
    "dec_banned_user": "已删除在 {umo} 对 {user} 的禁用（{time}），理由：{reason}",
    "dec_banned_user_global": "已删除全局对 {user} 的禁用（{time}），理由：{reason}",
    "dec_passed_user": "已删除在 {umo} 对 {user} 的临时解限（{time}），理由：{reason}",
    "dec_passed_user_global": "已删除全局对 {user} 的临时解限（{time}），理由：{reason}",
    "dec_no_record": "未找到记录，可能是因为该用户的记录已过期，无需删除",
    "dec_zerotime_error": "无法删除，因为该用户的记录时限被设为永久，请设置删除时间为0以强制删除！",
    "group_banned_list": "本群禁用的用户:",
    "no_group_banned": "\n本群没有禁用用户呢！",
    "group_passed_list": "本群临时解限用户：",
    "no_group_passed": "\n本群没有临时解限用户呢！",
    "global_banned_list": "全局禁用的用户:",
    "no_global_banned": "\n全局没有禁用用户",
    "global_passed_list": "全局临时解限用户：",
    "no_global_passed": "\n全局没有临时解限用户",
    "umo_banned_list": "禁用的会话：",
    "no_umo_banned": "\n没有禁用的会话呢！",
    "umo_passed_list": "临时解限的会话：",
    "no_umo_passed": "\n没有临时解限会话呢！",
    "no_reason": "无理由",
    "banlist_strlist_format": "\n - {id} - {time} - {reason}",
    "ban_reset_success": "已清除用户 {user} 的所有记录。",
    "ban_enabled": "已临时启用禁用功能～重启后失效",
    "ban_disabled": "已临时禁用禁用功能～重启后失效",
    # ---- 新增：SilenceBan 专属文案 ----
    "random_ban_success": "已在 {umo} 随机封禁用户 {user}，时长：{time}，理由：{reason}",
    "random_ban_invalid_range": "随机时长配置无效：最小时长({min_s})秒不能大于最大时长({max_s})秒，请检查插件配置。",
    "auto_ban_notice": "[自动封禁] 用户 {user} 因触发“不理你了”话术 {count} 次，已在 {umo} 被自动封禁，时长：{time}",
    "silence_triggered": "⚠️ LLM已对你说“不理你了” {count}/ {trigger_count} 次！再触发 {remaining} 次将被自动封禁。",
    "silence_counter_title": "“不理你了”话术计数器：",
    "silence_counter_no_data": "\n暂无计数数据。",
    "silence_counter_format": "\n - {umo} / {uid}: {count} 次",
    "auto_ban_disabled": "自动封禁功能未启用，话术计数器不会工作。",
    "help_text": """说不理你就不理你 插件使用指南：

🌸 基础命令：
{ban_help_cmd} - 查看这份指南

🚫 限制命令：
{ban_cmd} - 在会话限制用户（若会话内已存在限制，则叠加）
{ban_all_cmd} - 全局限制用户（若全局已存在限制，则叠加）
{dec_ban_cmd} - 删除在会话对用户禁用的时限
{dec_ban_all_cmd} - 删除全局对用户禁用的时限
{random_ban_cmd} - 随机时长封禁用户（时长在插件配置的区间内随机）

🎀 解限命令：
{pass_cmd} - 解除当前会话限制（允许临时解限，若已有解除时限，则叠加）
{pass_all_cmd} - 解除全局限制（允许临时解限，若已有解除时限，则叠加）
{dec_pass_cmd} - 删除在会话对用户临时解限的时限
{dec_pass_all_cmd} - 删除全局对用户临时解限的时限
{ban_reset_cmd} - 删除一名指定用户的所有记录

📒 查询命令：
{banlist_cmd} - 查看当前限制名单
{silence_counter_cmd} - 查看“不理你了”话术计数器

⚙️ 功能控制：
{ban_enable_cmd} - 启用限制功能
{ban_disable_cmd} - 停用限制功能

⏰ 时间格式说明：
- 数字+单位：1d(1天)/2h(2小时)/30m(30分钟)/10s(10秒)
- 若不填写或时长为 0，则为永久。

🤖 自动封禁说明：
- 当LLM回复“不理你了”或“真的不理你了”达到设定次数后，自动将用户封禁随机时长
- 随机时长区间可在插件配置界面设置

💡 注意事项：
- 只有管理员可以操作
- 永久限制/永久解除限制不支持叠加
- 群内设置优先于全局设置
- 过期限制会自动清理""",
}
