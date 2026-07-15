import random
import time as time_module
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, StarTools
from astrbot.api import logger, AstrBotConfig
from astrbot.api.provider import LLMResponse

from . import strings, time_utils
from .datafile_manager import DatafileManager
from .user_manager import (
    BaseModelList,
    BaseDataModel,
    UserDataList,
    UserDataModel,
    UmoDataModel,
    UmoDataList,
    ModelListRegistry,
    MODEL_LIST_REGISTRY,
)
from .event_utils import EventUtils
from .silence_tracker import detect_silence_phrase, get_trigger_phrases_display
from .exceptions import *


class SilenceBan(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        # 基础配置
        self.enable = config.get("enable", True)
        cache_ttl = config.get("cache_ttl", 60)

        # 话术自动封禁配置
        self.auto_ban_enable = config.get("auto_ban_enable", True)
        self.trigger_count = config.get("trigger_count", 2)
        self.min_random_ban_seconds = config.get("min_random_ban_seconds", 60)
        self.max_random_ban_seconds = config.get("max_random_ban_seconds", 86400)

        # 校验随机时长区间
        if self.min_random_ban_seconds > self.max_random_ban_seconds:
            logger.warning(
                f"随机时长配置无效：min({self.min_random_ban_seconds}) > max({self.max_random_ban_seconds})，"
                f"将交换两者"
            )
            self.min_random_ban_seconds, self.max_random_ban_seconds = (
                self.max_random_ban_seconds,
                self.min_random_ban_seconds,
            )

        MODEL_LIST_REGISTRY.start()
        self.data_manager = DatafileManager(
            StarTools.get_data_dir(), cache_ttl=cache_ttl
        )

    # ==================== 话术自动封禁（LLM 回复钩子） ====================

    def _get_random_ban_seconds(self) -> int:
        """获取随机封禁秒数"""
        return random.randint(self.min_random_ban_seconds, self.max_random_ban_seconds)

    @filter.on_llm_response()
    async def _on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        """
        LLM 回复钩子：检测 LLM 回复中是否包含"不理你了"/"真的不理你了"，
        若达到触发次数则自动封禁用户。
        注意：LLM 钩子中不能 yield，通过直接修改 resp.completion_text 来追加通知文本。
        """
        if not self.enable or not self.auto_ban_enable:
            return

        # 获取 LLM 回复文本（从 resp.completion_text 获取）
        response_text = ""
        try:
            response_text = resp.completion_text or ""
        except Exception:
            pass

        if not response_text:
            return

        # 检测是否包含触发短语
        if not detect_silence_phrase(response_text):
            return

        # 获取目标用户和会话（event 是触发此次 LLM 回复的原始用户消息）
        umo = event.unified_msg_origin
        uid = event.get_sender_id()

        if not uid or not umo:
            return

        # 自增计数器
        new_count = self.data_manager.increment_silence_counter(umo, uid)
        remaining = self.trigger_count - new_count

        logger.info(
            f"[SilenceBan] 检测到话术触发: umo={umo}, uid={uid}, count={new_count}/{self.trigger_count}"
        )

        if new_count >= self.trigger_count:
            # 达到触发次数，自动封禁
            random_seconds = self._get_random_ban_seconds()
            ban_time_str = time_utils.seconds_to_timestr(random_seconds)
            reason = f"自动封禁：LLM已对你说{get_trigger_phrases_display()} {self.trigger_count} 次"

            try:
                ban_list: dict[str, UserDataList] = self.data_manager.get_data("ban")
                if umo not in ban_list:
                    ban_list[umo] = UserDataList()

                new_ban_item = UserDataModel(
                    uid=uid,
                    time=int(time_module.time()) + random_seconds,
                    reason=reason,
                )
                ban_list[umo].append(new_ban_item)
                self.data_manager.write_data("ban", ban_list)

                # 重置计数器
                self.data_manager.reset_silence_counter(umo, uid)

                notice = strings.messages["auto_ban_notice"].format(
                    user=uid,
                    count=self.trigger_count,
                    umo=umo,
                    time=time_utils.time_format(ban_time_str),
                )
                logger.warning(notice)

                # 直接修改 LLM 回复文本，在其后追加封禁通知
                resp.completion_text = response_text + f"\n{notice}"

                # 阻止后续处理
                event.stop_event()
            except Exception as e:
                logger.error(f"[SilenceBan] 自动封禁失败: {e}")
        else:
            # 未达触发次数，在 LLM 回复文本后追加警告
            warning_msg = strings.messages["silence_triggered"].format(
                count=new_count,
                trigger_count=self.trigger_count,
                remaining=remaining,
            )
            resp.completion_text = response_text + f"\n{warning_msg}"

    # ==================== /random-ban 随机时长封禁 ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("random-ban")
    async def random_ban(
        self,
        event: AstrMessageEvent,
        banuser: str,
        umo: str | None = None,
        end: str | None = None,
    ):
        """
        以随机时长封禁指定用户。时长范围由管理员在插件界面配置。
        格式：/random-ban <@用户|UID（QQ号）> [UMO]
        """
        if end is not None:
            yield event.plain_result(strings.command_error("random-ban"))
            return
        if umo is None:
            umo = event.unified_msg_origin

        try:
            ban_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                ban_uid = event_at
            else:
                ban_uid = banuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("random-ban"))
            return

        # 校验随机时长区间
        if self.min_random_ban_seconds > self.max_random_ban_seconds:
            yield event.plain_result(
                strings.messages["random_ban_invalid_range"].format(
                    min_s=self.min_random_ban_seconds,
                    max_s=self.max_random_ban_seconds,
                )
            )
            return

        random_seconds = self._get_random_ban_seconds()
        ban_time_str = time_utils.seconds_to_timestr(random_seconds)
        reason = "随机时长封禁"

        banlist: dict[str, UserDataList] = self.data_manager.get_data("ban")
        if umo not in banlist:
            banlist[umo] = UserDataList()

        new_ban_item = UserDataModel(
            uid=ban_uid,
            time=int(time_module.time()) + random_seconds,
            reason=reason,
        )
        banlist[umo].append(new_ban_item)
        self.data_manager.write_data("ban", banlist)

        yield event.plain_result(
            strings.messages["random_ban_success"].format(
                umo=umo,
                user=ban_uid,
                time=time_utils.time_format(ban_time_str),
                reason=reason,
            )
        )

    # ==================== /silence-counter 查看话术计数器 ====================

    @filter.command("silence-counter")
    async def silence_counter_cmd(self, event: AstrMessageEvent):
        """
        查看当前话术计数器的状态
        """
        if not self.auto_ban_enable:
            yield event.plain_result(strings.messages["auto_ban_disabled"])
            return

        counter: dict[str, dict[str, int]] = self.data_manager.get_data("silence_counter")
        if not counter:
            yield event.plain_result(
                strings.messages["silence_counter_title"]
                + strings.messages["silence_counter_no_data"]
            )
            return

        lines = []
        for umo, users in counter.items():
            for uid, count in users.items():
                lines.append(
                    strings.messages["silence_counter_format"].format(
                        umo=umo, uid=uid, count=count
                    )
                )

        yield event.plain_result(
            strings.messages["silence_counter_title"] + "".join(lines)
        )

    # ==================== /banlist 查看封禁名单 ====================

    @filter.command("banlist")
    async def banlist(self, event: AstrMessageEvent):
        """显示当前禁用名单"""
        if not self.enable:
            group_banned_text = (
                strings.messages["group_banned_list"]
                + strings.messages["no_group_banned"]
            )
            global_banned_text = (
                strings.messages["global_banned_list"]
                + strings.messages["no_global_banned"]
            )
            group_passed_text = (
                strings.messages["group_passed_list"]
                + strings.messages["no_group_passed"]
            )
            global_passed_text = (
                strings.messages["global_passed_list"]
                + strings.messages["no_global_passed"]
            )
            umo_banned_text = (
                strings.messages["umo_banned_list"] + strings.messages["no_umo_banned"]
            )
            umo_passed_text = (
                strings.messages["umo_passed_list"] + strings.messages["no_umo_passed"]
            )
        else:
            umo = event.unified_msg_origin
            data: dict[str, dict[str, UserDataList] | BaseModelList] = (
                self.data_manager.get_data()
            )
            try:
                group_passed_list = data["pass"][umo]
            except KeyError:
                group_passed_list = UserDataList()
            global_passed_list: UserDataList = data["passall"]
            try:
                group_banned_list = data["ban"][umo]
            except KeyError:
                group_banned_list = UserDataList()
            global_banned_list: UserDataList = data["banall"]
            umo_passed_list: UmoDataList = data["umopass"]
            umo_banned_list: UmoDataList = data["umoban"]

            def _format_list(lst, empty_msg):
                formatted = [
                    strings.messages["banlist_strlist_format"].format(
                        id=item.uid if hasattr(item, "uid") else item.umo,
                        time=time_utils.timelast_format(
                            (item.time - int(time_module.time()))
                            if item.time != 0
                            else 0
                        ),
                        reason=item.reason
                        if item.reason
                        else strings.messages["no_reason"],
                    )
                    for item in lst
                ]
                if not formatted:
                    formatted.append(empty_msg)
                return formatted

            group_banned_str_list = _format_list(
                group_banned_list, strings.messages["no_group_banned"]
            )
            global_banned_str_list = _format_list(
                global_banned_list, strings.messages["no_global_banned"]
            )
            group_passed_str_list = _format_list(
                group_passed_list, strings.messages["no_group_passed"]
            )
            global_passed_str_list = _format_list(
                global_passed_list, strings.messages["no_global_passed"]
            )
            umo_banned_str_list = _format_list(
                umo_banned_list, strings.messages["no_umo_banned"]
            )
            umo_passed_str_list = _format_list(
                umo_passed_list, strings.messages["no_umo_passed"]
            )

            group_banned_text = strings.messages["group_banned_list"] + "".join(
                group_banned_str_list
            )
            global_banned_text = strings.messages["global_banned_list"] + "".join(
                global_banned_str_list
            )
            group_passed_text = strings.messages["group_passed_list"] + "".join(
                group_passed_str_list
            )
            global_passed_text = strings.messages["global_passed_list"] + "".join(
                global_passed_str_list
            )
            umo_banned_text = strings.messages["umo_banned_list"] + "".join(
                umo_banned_str_list
            )
            umo_passed_text = strings.messages["umo_passed_list"] + "".join(
                umo_passed_str_list
            )

        result = f"{group_banned_text}\n\n{global_banned_text}\n\n{group_passed_text}\n\n{global_passed_text}\n\n{umo_banned_text}\n\n{umo_passed_text}"
        yield event.plain_result(result)

    # ==================== /ban-help ====================

    @filter.command("ban-help")
    async def ban_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = strings.messages["help_text"].format(
            ban_help_cmd=strings.commands["ban-help"],
            ban_cmd=strings.commands["ban"],
            ban_all_cmd=strings.commands["ban-all"],
            dec_ban_cmd=strings.commands["dec-ban"],
            dec_ban_all_cmd=strings.commands["dec-ban-all"],
            random_ban_cmd=strings.commands["random-ban"],
            pass_cmd=strings.commands["pass"],
            pass_all_cmd=strings.commands["pass-all"],
            dec_pass_cmd=strings.commands["dec-pass"],
            dec_pass_all_cmd=strings.commands["dec-pass-all"],
            ban_reset_cmd=strings.commands["ban-reset"],
            banlist_cmd=strings.commands["banlist"],
            silence_counter_cmd=strings.commands["silence-counter"],
            ban_enable_cmd=strings.commands["ban-enable"],
            ban_disable_cmd=strings.commands["ban-disable"],
        )
        yield event.plain_result(help_text)

    # ==================== /ban-enable /ban-disable ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("ban-enable")
    async def ban_enable(self, event: AstrMessageEvent):
        self.enable = True
        yield event.plain_result(strings.messages["ban_enabled"])
        logger.warning(
            f"已临时启用禁用功能(in {event.unified_msg_origin} - {event.get_sender_name()}({event.get_sender_id()}))"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("ban-disable")
    async def ban_disable(self, event: AstrMessageEvent):
        self.enable = False
        yield event.plain_result(strings.messages["ban_disabled"])
        logger.warning(
            f"已临时禁用禁用功能(in {event.unified_msg_origin} - {event.get_sender_name()}({event.get_sender_id()}))"
        )

    # ==================== /ban ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("ban")
    async def ban_user(
        self,
        event: AstrMessageEvent,
        banuser: str,
        time: str = "0",
        reason: str | None = None,
        umo: str | None = None,
        end: str | None = None,
    ):
        if end is not None:
            yield event.plain_result(strings.command_error("ban"))
            return
        if umo is None:
            umo = event.unified_msg_origin
        reason = strings.noreason_to_none(reason)
        try:
            ban_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                ban_uid = event_at
            else:
                ban_uid = banuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("ban"))
            return

        banlist: dict[str, UserDataList] = self.data_manager.get_data("ban")
        if umo not in banlist:
            banlist[umo] = UserDataList()
        group_banned_list: UserDataList = banlist[umo]

        try:
            update_time: int = time_utils.timestr_to_int(time)
            if not group_banned_list.add_time_to_data(ban_uid, update_time, reason):
                new_ban_item = UserDataModel(
                    uid=ban_uid,
                    time=(
                        (int(time_module.time()) + update_time)
                        if update_time != 0
                        else 0
                    ),
                    reason=reason,
                )
                group_banned_list.append(new_ban_item)
            self.data_manager.write_data("ban", banlist)
        except PermanentRecordTimeError:
            yield event.plain_result(
                strings.messages["time_zeroset_error"].format(command="ban")
            )
            return
        except TimestrValueError as e:
            yield event.plain_result(
                strings.messages["invalid_timestr_error"].format(
                    timestr=e.invalid_timestr
                )
            )
            return

        yield event.plain_result(
            strings.messages["banned_user"].format(
                umo=umo,
                user=ban_uid,
                time=time_utils.time_format(time),
                reason=strings.reason_format(reason),
            )
        )

    # ==================== /ban-all ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("ban-all")
    async def ban_all(
        self,
        event: AstrMessageEvent,
        banuser: str,
        time: str = "0",
        reason: str | None = None,
        end: str | None = None,
    ):
        if end is not None:
            yield event.plain_result(strings.command_error("ban-all"))
            return
        reason = strings.noreason_to_none(reason)
        try:
            ban_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                ban_uid = event_at
            else:
                ban_uid = banuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("ban-all"))
            return

        banall_list: UserDataList = self.data_manager.get_data("banall")
        try:
            update_time: int = time_utils.timestr_to_int(time)
            if not banall_list.add_time_to_data(ban_uid, update_time, reason):
                new_ban_item = UserDataModel(
                    uid=ban_uid,
                    time=(
                        (int(time_module.time()) + update_time)
                        if update_time != 0
                        else 0
                    ),
                    reason=reason,
                )
                banall_list.append(new_ban_item)
            self.data_manager.write_data("banall", banall_list)
        except PermanentRecordTimeError:
            yield event.plain_result(
                strings.messages["time_zeroset_error"].format(command="ban-all")
            )
            return
        except TimestrValueError as e:
            yield event.plain_result(
                strings.messages["invalid_timestr_error"].format(
                    timestr=e.invalid_timestr
                )
            )
            return

        yield event.plain_result(
            strings.messages["banned_user_global"].format(
                user=ban_uid,
                time=time_utils.time_format(time),
                reason=strings.reason_format(reason),
            )
        )

    # ==================== /pass ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("pass")
    async def pass_user(
        self,
        event: AstrMessageEvent,
        passuser: str,
        time: str = "0",
        reason: str | None = None,
        umo: str | None = None,
        end: str | None = None,
    ):
        if end is not None:
            yield event.plain_result(strings.command_error("pass"))
            return
        if umo is None:
            umo = event.unified_msg_origin
        reason = strings.noreason_to_none(reason)
        try:
            pass_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                pass_uid = event_at
            else:
                pass_uid = passuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("pass"))
            return

        passlist: dict[str, UserDataList] = self.data_manager.get_data("pass")
        if umo not in passlist:
            passlist[umo] = UserDataList()
        group_passed_list: UserDataList = passlist[umo]

        try:
            update_time: int = time_utils.timestr_to_int(time)
            if not group_passed_list.add_time_to_data(pass_uid, update_time, reason):
                new_pass_item = UserDataModel(
                    uid=pass_uid,
                    time=(
                        (int(time_module.time()) + update_time)
                        if update_time != 0
                        else 0
                    ),
                    reason=reason,
                )
                group_passed_list.append(new_pass_item)
            self.data_manager.write_data("pass", passlist)
        except PermanentRecordTimeError:
            yield event.plain_result(
                strings.messages["time_zeroset_error"].format(command="pass")
            )
            return
        except TimestrValueError as e:
            yield event.plain_result(
                strings.messages["invalid_timestr_error"].format(
                    timestr=e.invalid_timestr
                )
            )
            return

        yield event.plain_result(
            strings.messages["passed_user"].format(
                umo=umo,
                user=pass_uid,
                time=time_utils.time_format(time),
                reason=strings.reason_format(reason),
            )
        )

    # ==================== /pass-all ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("pass-all")
    async def pass_all(
        self,
        event: AstrMessageEvent,
        passuser: str,
        time: str = "0",
        reason: str | None = None,
        end: str | None = None,
    ):
        if end is not None:
            yield event.plain_result(strings.command_error("pass-all"))
            return
        reason = strings.noreason_to_none(reason)
        try:
            pass_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                pass_uid = event_at
            else:
                pass_uid = passuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("pass-all"))
            return

        passall_list: UserDataList = self.data_manager.get_data("passall")
        try:
            update_time: int = time_utils.timestr_to_int(time)
            if not passall_list.add_time_to_data(pass_uid, update_time, reason):
                new_pass_item = UserDataModel(
                    uid=pass_uid,
                    time=(
                        (int(time_module.time()) + update_time)
                        if update_time != 0
                        else 0
                    ),
                    reason=reason,
                )
                passall_list.append(new_pass_item)
            self.data_manager.write_data("passall", passall_list)
        except PermanentRecordTimeError:
            yield event.plain_result(
                strings.messages["time_zeroset_error"].format(command="pass-all")
            )
            return
        except TimestrValueError as e:
            yield event.plain_result(
                strings.messages["invalid_timestr_error"].format(
                    timestr=e.invalid_timestr
                )
            )
            return

        yield event.plain_result(
            strings.messages["passed_user_global"].format(
                user=pass_uid,
                time=time_utils.time_format(time),
                reason=strings.reason_format(reason),
            )
        )

    # ==================== /dec-ban ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dec-ban")
    async def dec_ban(
        self,
        event: AstrMessageEvent,
        banuser: str,
        time: str = "0",
        reason: str | None = None,
        umo: str | None = None,
        end: str | None = None,
    ):
        if end is not None:
            yield event.plain_result(strings.command_error("dec-ban"))
            return
        if umo is None:
            umo = event.unified_msg_origin
        reason = strings.noreason_to_none(reason)
        try:
            ban_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                ban_uid = event_at
            else:
                ban_uid = banuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("dec-ban"))
            return

        ban_list: dict[str, UserDataList] = self.data_manager.get_data("ban")
        group_banned_list: UserDataList = ban_list.get(umo, UserDataList())
        try:
            remove_time: int = time_utils.timestr_to_int(time)
            if not group_banned_list.subtract_time_from_data(
                ban_uid, remove_time, reason
            ):
                yield event.plain_result(strings.messages["dec_no_record"])
                return
            self.data_manager.write_data("ban", ban_list)
        except PermanentRecordTimeError:
            yield event.plain_result(strings.messages["dec_zerotime_error"])
            return
        except TimestrValueError as e:
            yield event.plain_result(
                strings.messages["invalid_timestr_error"].format(
                    timestr=e.invalid_timestr
                )
            )
            return

        yield event.plain_result(
            strings.messages["dec_banned_user"].format(
                user=ban_uid,
                time=time_utils.time_format(time),
                reason=strings.reason_format(reason),
                umo=umo,
            )
        )

    # ==================== /dec-ban-all ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dec-ban-all")
    async def dec_ban_all(
        self,
        event: AstrMessageEvent,
        banuser: str,
        time: str = "0",
        reason: str | None = None,
        end: str | None = None,
    ):
        if end is not None:
            yield event.plain_result(strings.command_error("dec-ban-all"))
            return
        reason = strings.noreason_to_none(reason)
        try:
            ban_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                ban_uid = event_at
            else:
                ban_uid = banuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("dec-ban-all"))
            return

        banall_list: UserDataList = self.data_manager.get_data("banall")
        try:
            remove_time: int = time_utils.timestr_to_int(time)
            if not banall_list.subtract_time_from_data(ban_uid, remove_time, reason):
                yield event.plain_result(strings.messages["dec_no_record"])
                return
            self.data_manager.write_data("banall", banall_list)
        except PermanentRecordTimeError:
            yield event.plain_result(strings.messages["dec_zerotime_error"])
            return
        except TimestrValueError as e:
            yield event.plain_result(
                strings.messages["invalid_timestr_error"].format(
                    timestr=e.invalid_timestr
                )
            )
            return

        yield event.plain_result(
            strings.messages["dec_banned_user_global"].format(
                user=ban_uid,
                time=time_utils.time_format(time),
                reason=strings.reason_format(reason),
            )
        )

    # ==================== /dec-pass ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dec-pass")
    async def dec_pass(
        self,
        event: AstrMessageEvent,
        passuser: str,
        time: str = "0",
        reason: str | None = None,
        umo: str | None = None,
        end: str | None = None,
    ):
        if end is not None:
            yield event.plain_result(strings.command_error("dec-pass"))
            return
        if umo is None:
            umo = event.unified_msg_origin
        reason = strings.noreason_to_none(reason)
        try:
            pass_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                pass_uid = event_at
            else:
                pass_uid = passuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("dec-pass"))
            return

        pass_list: dict[str, UserDataList] = self.data_manager.get_data("pass")
        group_passed_list: UserDataList = pass_list.get(umo, UserDataList())
        try:
            remove_time: int = time_utils.timestr_to_int(time)
            if not group_passed_list.subtract_time_from_data(
                pass_uid, remove_time, reason
            ):
                yield event.plain_result(strings.messages["dec_no_record"])
                return
            self.data_manager.write_data("pass", pass_list)
        except PermanentRecordTimeError:
            yield event.plain_result(strings.messages["dec_zerotime_error"])
            return
        except TimestrValueError as e:
            yield event.plain_result(
                strings.messages["invalid_timestr_error"].format(
                    timestr=e.invalid_timestr
                )
            )
            return

        yield event.plain_result(
            strings.messages["dec_passed_user"].format(
                umo=umo,
                user=pass_uid,
                time=time_utils.time_format(time),
                reason=strings.reason_format(reason),
            )
        )

    # ==================== /dec-pass-all ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("dec-pass-all")
    async def dec_pass_all(
        self,
        event: AstrMessageEvent,
        passuser: str,
        time: str = "0",
        reason: str | None = None,
        end: str | None = None,
    ):
        if end is not None:
            yield event.plain_result(strings.command_error("dec-pass-all"))
            return
        reason = strings.noreason_to_none(reason)
        try:
            pass_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                pass_uid = event_at
            else:
                pass_uid = passuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("dec-pass-all"))
            return

        passall_list: UserDataList = self.data_manager.get_data("passall")
        try:
            remove_time: int = time_utils.timestr_to_int(time)
            if not passall_list.subtract_time_from_data(pass_uid, remove_time, reason):
                yield event.plain_result(strings.messages["dec_no_record"])
                return
            self.data_manager.write_data("passall", passall_list)
        except PermanentRecordTimeError:
            yield event.plain_result(strings.messages["dec_zerotime_error"])
            return
        except TimestrValueError as e:
            yield event.plain_result(
                strings.messages["invalid_timestr_error"].format(
                    timestr=e.invalid_timestr
                )
            )
            return

        yield event.plain_result(
            strings.messages["dec_passed_user_global"].format(
                user=pass_uid,
                time=time_utils.time_format(time),
                reason=strings.reason_format(reason),
            )
        )

    # ==================== /ban-reset ====================

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("ban-reset")
    async def ban_reset(
        self, event: AstrMessageEvent, resetuser: str, end: str | None = None
    ):
        if end is not None:
            yield event.plain_result(strings.command_error("ban-reset"))
            return
        try:
            reset_uid: str
            event_at: str | None = EventUtils.get_event_at(event)
            if event_at:
                reset_uid = event_at
            else:
                reset_uid = resetuser
        except AtUserCountError:
            yield event.plain_result(strings.command_error("ban-reset"))
            return

        user_datas: dict[str, dict[str, UserDataList] | BaseModelList] = (
            self.data_manager.get_data(["ban", "pass", "banall", "passall"])
        )
        for umo in list(user_datas["ban"].keys()):
            user_datas["ban"][umo].remove_by_id(reset_uid)
        for umo in list(user_datas["pass"].keys()):
            user_datas["pass"][umo].remove_by_id(reset_uid)
        user_datas["banall"].remove_by_id(reset_uid)
        user_datas["passall"].remove_by_id(reset_uid)
        self.data_manager.write_data(list(user_datas.keys()), list(user_datas.values()))

        yield event.plain_result(
            strings.messages["ban_reset_success"].format(user=reset_uid)
        )

    # ==================== 全局事件过滤器 ====================

    @filter.event_message_type(filter.EventMessageType.ALL, priority=114)
    async def filter_banned_users(self, event: AstrMessageEvent):
        """
        全局事件过滤器：
        如果禁用功能启用且发送者被禁用，则停止事件传播，机器人不再响应该用户的消息。
        """
        if EventUtils.is_banned(self.enable, self.data_manager, event)[0]:
            event.stop_event()

    async def terminate(self):
        """插件被卸载/停用时会调用"""
        MODEL_LIST_REGISTRY.stop_event.set()
