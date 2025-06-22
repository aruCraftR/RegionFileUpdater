import os
import shutil
import time
import json as jsonlib
from typing import Iterable, Optional

from mcdreforged.api.all import (
    ServerInterface,
    Serializable,
    PluginServerInterface,
    CommandSource,
    serialize,
    PlayerCommandSource,
    new_thread,
    Integer,
    UnknownArgument,
    Literal,
    RequirementNotMet,
)

PLUGIN_METADATA = (
    ServerInterface.get_instance().as_plugin_server_interface().get_self_metadata()
)


class Config(Serializable):
    enabled: bool = True
    protected_region_file_name = "protected-regions.json"
    source_world_directory: str = "./qb_multi/slot1/world"
    destination_world_directory: str = "./server/world"
    dimension_region_folder: dict[str, str | list[str]] = {
        "-1": ["DIM-1/region", "DIM-1/poi"],
        "0": ["region", "poi"],
        "1": ["DIM1/region", "DIM1/poi"],
    }


config: Config | None = None
Prefix = "!!region"
PluginName = PLUGIN_METADATA.name
LogFilePath = os.path.join("logs", f"{PluginName}.log")
HelpMessage = """
------MCDR {1} v{2}------
一个从指定位置拉取region文件至本服存档的插件
§a【指令说明】§r
§7{0} §r显示帮助信息
§7{0} add §r添加玩家所在位置的区域文件
§7{0} add §6[x] [z] [d] §r添加指定的区域文件
§7{0} del §r删除玩家所在位置的区域文件
§7{0} del §6[d] [x] [z] [d] §r删除指定的区域文件
§7{0} del-all §r删除所有区域文件
§7{0} protect §r将玩家所在位置的区域文件设为保护状态
§7{0} protect §6[x] [z] [d] §r保护指定的区域文件
§7{0} deprotect §r取消保护玩家所在位置的区域文件
§7{0} deprotect §6[x] [z] [d] §r取消保护指定的区域文件
§7{0} deprotect-all §r取消保护所有的区域文件
§7{0} list §r列出待更新的区域文件
§7{0} list-protect §r列出受保护的区域文件
§7{0} history §r输出上一次update的结果
§7{0} update §r更新列表中的区域文件, 这将重启服务器
§7{0} reload §r重新载入配置文件
§a【参数说明】§r
§6[x] [z]§r: 区域文件坐标, 如r.-3.1.mca的区域文件坐标为x=-3 z=1
§6[d]§r: 维度序号, 主世界为0, 下界为-1, 末地为1
""".strip().format(Prefix, PLUGIN_METADATA.name, PLUGIN_METADATA.version)

regionList: list["Region"] = []
protectedRegionList: list["Region"] = []
historyList: list[tuple["Region", bool]] = []
server_inst: PluginServerInterface


class Region(Serializable):
    def __init__(self, x: int, z: int, dim: int):
        self.x = x
        self.z = z
        self.dim = dim

    def to_file_name(self):
        return f"r.{self.x}.{self.z}.mca"

    def to_file_list(self):
        file_list = []
        folders = config.dimension_region_folder[str(self.dim)]
        if isinstance(folders, str):
            file_list.append(os.path.join(folders, self.to_file_name()))
        elif isinstance(folders, Iterable):
            file_list.extend(
                os.path.join(folder, self.to_file_name()) for folder in folders
            )
        return file_list

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False
        return self.x == other.x and self.z == other.z and self.dim == other.dim

    def __repr__(self):
        return f"Region[x={self.x}, z={self.z}, dim={self.dim}]"


def print_log(server: ServerInterface, msg: str):
    server.logger.info(msg)
    try:
        with open(LogFilePath, "a") as logfile:
            logfile.write(
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
                + ": "
                + msg
                + "\n"
            )
    except Exception as e:
        server.logger.error(f"无法写入日志文件: {e}")


def add_region(source: CommandSource, region: Region):
    if region in regionList:
        source.reply("列表中已存在该区域文件")
    elif region not in protectedRegionList:
        regionList.append(region)
        source.reply(f"区域文件§6{region}§r已添加")


def delete_region(source: CommandSource, region: Region):
    if region not in regionList:
        source.reply("列表中不存在该区域文件")
    else:
        regionList.remove(region)
        source.reply(f"区域文件§6{region}§r已删除")


def clean_region_list(source: CommandSource):
    regionList.clear()
    source.reply("区域文件列表已清空")


def protect_region(source: CommandSource, region: Region):
    if region in protectedRegionList:
        source.reply("该区域文件已设保护")
        return
    protectedRegionList.append(region)
    if region in regionList:
        regionList.remove(region)
        source.reply(f"区域文件§6{region}§r已从列表移除并设保护")
    else:
        source.reply(f"区域文件§6{region}§r已设保护")
    save_protected_region_file()


def deprotect_region(source: CommandSource, region: Region):
    if region in protectedRegionList:
        protectedRegionList.remove(region)
        source.reply(f"区域文件§6{region}§r已取消保护")
        save_protected_region_file()
    else:
        source.reply("该区域文件未被保护")


def deprotect_all_regions(source: CommandSource):
    protectedRegionList.clear()
    source.reply("所有受保护区域文件已去保护")
    save_protected_region_file()


def save_protected_region_file():
    file_path = os.path.join(
        config.destination_world_directory, config.protected_region_file_name
    )
    with open(file_path, "w", encoding="utf8") as file:
        jsonlib.dump(serialize(protectedRegionList), file)


def load_protected_region_file():
    global protectedRegionList
    file_path = os.path.join(
        config.destination_world_directory, config.protected_region_file_name
    )
    if os.path.isfile(file_path):
        with open(file_path, "r", encoding="utf8") as file:
            try:
                protected_list_data = jsonlib.load(file)
            except Exception as e:
                server_inst.logger.error(
                    f"Fail to load protected regions from {file_path}: {e}"
                )
                protectedRegionList = []
                save_protected_region_file()
            else:
                protectedRegionList.extend(
                    Region(r["x"], r["z"], r["dim"]) for r in protected_list_data
                )


def get_region_from_source(source: PlayerCommandSource) -> Region:
    api = source.get_server().get_plugin_instance("minecraft_data_api")
    coord = api.get_player_coordinate(source.player)
    dim = api.get_player_dimension(source.player)
    return Region(int(coord.x) // 512, int(coord.z) // 512, dim)


@new_thread(PLUGIN_METADATA.name)
def add_region_from_player(source: CommandSource):
    if isinstance(source, PlayerCommandSource):
        add_region(source, get_region_from_source(source))
    else:
        source.reply("该指令仅支持玩家执行")


@new_thread(PLUGIN_METADATA.name)
def delete_region_from_player(source: CommandSource):
    if isinstance(source, PlayerCommandSource):
        delete_region(source, get_region_from_source(source))
    else:
        source.reply("该指令仅支持玩家执行")


@new_thread(PLUGIN_METADATA.name)
def protect_region_from_player(source: CommandSource):
    if isinstance(source, PlayerCommandSource):
        protect_region(source, get_region_from_source(source))
    else:
        source.reply("该指令仅支持玩家执行")


@new_thread(PLUGIN_METADATA.name)
def deprotect_region_from_player(source: CommandSource):
    if isinstance(source, PlayerCommandSource):
        deprotect_region(source, get_region_from_source(source))
    else:
        source.reply("该指令仅支持玩家执行")


def show_region_list(source: CommandSource):
    source.reply(f"更新列表中共有{len(regionList)}个待更新的区域文件")
    for region in regionList:
        source.reply(f"- §6{region}§r")


def show_history(source: CommandSource):
    source.reply(f"上次尝试更新更新了{len(historyList)}个区域文件")
    msg = {False: "失败", True: "成功"}
    for region, flag in historyList:
        source.reply(f"§6{region}§r: {msg[flag]}")


def show_protected_regions(source: CommandSource):
    source.reply(f"已保护区域列表中共有{len(protectedRegionList)}个受保护的区域文件")
    for region in protectedRegionList:
        source.reply(f"- §6{region}§r")


@new_thread(PLUGIN_METADATA.name)
def region_update(source: CommandSource):
    show_region_list(source)
    countdown = 5
    source.reply(
        f"[{PluginName}]: {countdown}秒后重启服务器更新列表中的区域文件",
        isBroadcast=True,
    )
    for i in range(1, countdown):
        source.reply(f"[{PluginName}]: 还有{countdown - i}秒", isBroadcast=True)
        time.sleep(1)

    source.get_server().stop()
    source.get_server().wait_for_start()

    print_log(source.get_server(), f"{source} 更新了 {len(regionList)} 个区域文件：")
    historyList.clear()
    for region in regionList:
        for region_file in region.to_file_list():
            src_file = os.path.join(config.source_world_directory, region_file)
            dest_file = os.path.join(config.destination_world_directory, region_file)
            try:
                if not os.path.isfile(src_file) and os.path.isfile(dest_file):
                    os.remove(dest_file)
                    source.get_server().logger.info(f'- *deleted* -> "{src_file}"')
                else:
                    source.get_server().logger.info(f'- "{src_file}" -> "{dest_file}"')
                    shutil.copyfile(src_file, dest_file)
            except Exception as e:
                msg = f"失败，错误信息：{str(e)}"
                flag = False
            else:
                msg = "成功"
                flag = True
            historyList.append((region, flag))
            print_log(source.get_server(), f"  {region}: {msg}")

    regionList.clear()
    time.sleep(1)
    source.get_server().start()


def on_load(server: PluginServerInterface, old):
    try:
        global historyList, regionList, protectedRegionList
        historyList = old.historyList
        regionList = old.regionList
    except AttributeError:
        pass

    global server_inst
    server_inst = server
    load_config(None)
    load_protected_region_file()
    register_commands(server)
    server.register_help_message(Prefix, "从指定存档处更新region文件至本服")


def load_config(source: Optional[CommandSource]):
    global config, server_inst
    config_file_path = os.path.join("config", f"{PLUGIN_METADATA.id}.json")
    config = server_inst.load_config_simple(
        config_file_path,
        in_data_folder=False,
        source_to_reply=source,
        echo_in_console=False,
        target_class=Config,
    )  # type: ignore


def reload_config(source: CommandSource):
    source.reply("重载配置文件中")
    load_config(source)


def register_commands(server: PluginServerInterface):
    def get_region_parm_node(callback):
        return Integer("x").then(
            Integer("z").then(Integer("dim").in_range(-1, 1).runs(callback))
        )

    server.register_command(
        Literal(Prefix)
        .runs(lambda src: src.reply(HelpMessage))
        .on_error(
            UnknownArgument,
            lambda src: src.reply(
                "参数错误！请输入§7{}§r以获取插件帮助".format(Prefix)
            ),
            handled=True,
        )
        .then(
            Literal("add")
            .runs(add_region_from_player)
            .then(
                get_region_parm_node(
                    lambda src, ctx: add_region(
                        src, Region(ctx["x"], ctx["z"], ctx["dim"])
                    )
                )
            )
        )
        .then(
            Literal("del")
            .runs(delete_region_from_player)
            .then(
                get_region_parm_node(
                    lambda src, ctx: delete_region(
                        src, Region(ctx["x"], ctx["z"], ctx["dim"])
                    )
                )
            )
        )
        .then(Literal("del-all").runs(clean_region_list))
        .then(
            Literal("protect")
            .runs(protect_region_from_player)
            .then(
                get_region_parm_node(
                    lambda src, ctx: protect_region(
                        src, Region(ctx["x"], ctx["z"], ctx["dim"])
                    )
                )
            )
        )
        .then(
            Literal("deprotect")
            .runs(deprotect_region_from_player)
            .then(
                get_region_parm_node(
                    lambda src, ctx: deprotect_region(
                        src, Region(ctx["x"], ctx["z"], ctx["dim"])
                    )
                )
            )
        )
        .then(Literal("list").runs(show_region_list))
        .then(Literal("list-protect").runs(show_protected_regions))
        .then(Literal("history").runs(show_history))
        .then(
            Literal("update")
            .requires(lambda: config.enabled)
            .on_error(
                RequirementNotMet,
                lambda src: src.reply(
                    "{}未启用！请在配置文件中开启".format(PLUGIN_METADATA.name)
                ),
                handled=True,
            )
            .runs(region_update)
        )
        .then(Literal("reload").runs(reload_config))
    )
