"""
任务注册表 — GUI「开始执行」和 CLI `--run` 共用。

面板点开始 = 调这里的 runner；命令行同样调。
新增副本：在 TASKS 加一行即可。
"""
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class TaskSpec:
    id: str
    label: str
    runner: str          # "module:function"
    # CLI 可传参数。value 是 argparse dest。
    options: tuple = ()  # ((flag, dest, help, default), ...)


TASKS = {
    "zhuxian": TaskSpec(
        id="zhuxian",
        label="主线",
        runner="core.daily.zhuxian_battle:run_zhuxian_battle",
        options=(
            ("--stop", "stop_stage", "打到哪一关，如 4-7", "4-7"),
            ("--from-home", "from_home", "从主界面进入（默认开）", True),
            ("--no-from-home", "from_home", "已经在章节/地图里，跳过入口", False),
            ("--preset", "use_preset", "上场套预设", False),
        ),
    ),
    "zhike": TaskSpec(
        id="zhike",
        label="智壳",
        runner="core.daily.zhike_battle:run_zhike_battle",
        options=(
            ("--name", "character_name", "角色名", ""),
            ("--diff", "difficulty", "难度", "炼狱"),
            ("--streak", "streak", "场次", 1),
        ),
    ),
    "yuanqi": TaskSpec(
        id="yuanqi",
        label="源器",
        runner="core.daily.yuanqi_battle:run_yuanqi_battle",
        options=(
            ("--name", "character_name", "角色名", ""),
            ("--diff", "difficulty", "难度", "地狱四"),
            ("--streak", "streak", "场次", 1),
        ),
    ),
    "qianneng": TaskSpec(
        id="qianneng",
        label="潜能/经验",
        runner="core.daily.qianneng_battle:run_qianneng_battle",
        options=(
            ("--name", "character_name", "副本名", ""),
            ("--diff", "difficulty", "难度", ""),
            ("--streak", "streak", "场次", 1),
        ),
    ),
    "guild-arena": TaskSpec("guild-arena", "竞技场自动", "core.daily.guild_battle:run_guild_arena"),
    "guild-signin": TaskSpec("guild-signin", "公会签到", "core.daily.guild_battle:run_guild_signin"),
    "guild-anchor": TaskSpec("guild-anchor", "锚点勘测", "core.daily.guild_battle:run_guild_anchor"),
    "guild-weekly": TaskSpec("guild-weekly", "公会每周领取", "core.daily.guild_battle:run_guild_weekly"),
    "guild-assist": TaskSpec("guild-assist", "协会共助", "core.daily.guild_battle:run_guild_assist"),
    "guild-theater": TaskSpec("guild-theater", "幻音剧场", "core.daily.guild_battle:run_guild_theater"),
    "guild-claim-all": TaskSpec("guild-claim-all", "任务一键领取", "core.daily.guild_battle:run_guild_claim_all"),
    "anlong": TaskSpec(
        id="anlong", label="暗笼激斗",
        runner="core.events.anlong_battle:run_anlong_battle",
        options=(("--streak", "streak", "场次", 1),),
    ),
    "chaoneng": TaskSpec(
        id="chaoneng", label="超能二十一",
        runner="core.events.chaoneng_battle:run_chaoneng_battle",
        options=(("--streak", "streak", "局数", 1),),
    ),
    "yuanwang": TaskSpec("yuanwang", "源网征令", "core.events.yuanwang_battle:run_yuanwang_battle"),
    "xujin": TaskSpec("xujin", "虚烬探索", "core.events.xujin_battle:run_xujin_battle"),
    "rta": TaskSpec(
        id="rta", label="RTA每周",
        runner="core.rta.weekly_battle:run_rta_weekly_battle",
        options=(("--streak", "streak", "局数", 1),),
    ),
}


def load_runner(spec: TaskSpec) -> Callable:
    module_name, func_name = spec.runner.split(":")
    import importlib
    mod = importlib.import_module(module_name)
    return getattr(mod, func_name)


def run_task(bot, task_id: str, **kwargs) -> bool:
    spec = TASKS.get(task_id)
    if spec is None:
        raise KeyError(f"未知任务: {task_id}，可用: {', '.join(TASKS)}")
    fn = load_runner(spec)
    # 只把函数认识的参数传进去
    import inspect
    sig = inspect.signature(fn)
    accepted = {k: v for k, v in kwargs.items() if k in sig.parameters}
    try:
        return fn(bot, **accepted)
    except Exception as e:
        # 失败现场包（P0A）：注册表是全部任务的统一出口，异常即落包再原样抛出
        from core._base import scene_pack
        scene_pack.write_scene_pack(
            task=task_id, node=f"注册表任务 {task_id}",
            error=e, bot=bot, extra={"参数": accepted})
        raise
