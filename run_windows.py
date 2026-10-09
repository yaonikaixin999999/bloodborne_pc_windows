# Windows port modifications by yaonikaixin999999, 2026-10-05.
# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows launcher for the native bbport experiment. Requires the user's game dump."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

FROZEN=getattr(sys,'frozen',False)
# 冻结成 exe 后 __file__ 不再是源码路径：数据根（user/、out/、bbport.ini）取 exe
# 所在目录，脚本模块由 PyInstaller 内嵌加载；源码模式行为不变。
ROOT=Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'scripts'))
from prepare import sfo
from patches import read_settings,scaled_sizes
from windows_graphics import load_settings,save_settings

PROFILES={
    '1080p':('1920x1080',1),
    '1440p':('2560x1440',1),
    '4k':('3840x2160',2),
    '4k-quality':('3840x2160',1),
    '4k-native':('3840x2160',0),
}
SUPPORTED_TITLES=('CUSA03173','CUSA03023')
LANGUAGES={'auto':None,'zh-cn':11,'zh-tw':10,'en':1}
LANGUAGE_LABELS={'自动（优先中文）':'auto','简体中文':'zh-cn','繁体中文':'zh-tw','English':'en'}
CONTROLLER_SWAPS={'ps4':(False,False),'swap-ab':(True,False),
                  'swap-xy':(False,True),'xbox':(True,True)}
CONTROLLER_LAYOUTS=tuple(CONTROLLER_SWAPS)
CONTROLLER_HINTS={'ps4':'当前对应：A=✕，B=○，X=□，Y=△',
                  'swap-ab':'当前对应：A=○，B=✕，X=□，Y=△',
                  'swap-xy':'当前对应：A=✕，B=○，X=△，Y=□',
                  'xbox':'当前对应：A=○，B=✕，X=△，Y=□'}
FPS_LABELS={'30 帧 · 原版':'30','60 帧 · 推荐':'60','90 帧 · 实验':'90',
            '跟随显示器（最高 120 帧）· 实验':'uncap'}
FPS_CHOICES=tuple(FPS_LABELS.values())

def read_preferences():
    preferences={'game_dir':'','resolution':'1080p','language':'auto','fullscreen':False,
                 'controller_layout':'ps4','fps':'60','vsync':False,'sync_refresh':False}
    # Older launchers only saved launch.json. Recover the last profile on upgrade,
    # then prefer choices saved by the current launcher's window or command line.
    for path in (ROOT/'out/windows-data/launch.json',ROOT/'user/launcher.json'):
        try:
            saved=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            continue
        if not isinstance(saved,dict): continue
        if isinstance(saved.get('game_dir'),str): preferences['game_dir']=saved['game_dir']
        if isinstance(saved.get('resolution'),str) and saved['resolution'] in PROFILES:
            preferences['resolution']=saved['resolution']
        if isinstance(saved.get('language'),str) and saved['language'] in LANGUAGES:
            preferences['language']=saved['language']
        if isinstance(saved.get('fullscreen'),bool): preferences['fullscreen']=saved['fullscreen']
        if isinstance(saved.get('vsync'),bool): preferences['vsync']=saved['vsync']
        if isinstance(saved.get('sync_refresh'),bool): preferences['sync_refresh']=saved['sync_refresh']
        if isinstance(saved.get('controller_layout'),str) and saved['controller_layout'] in CONTROLLER_LAYOUTS:
            preferences['controller_layout']=saved['controller_layout']
        if isinstance(saved.get('fps'),str) and saved['fps'] in FPS_CHOICES:
            preferences['fps']=saved['fps']
    game=Path(preferences['game_dir']) if preferences['game_dir'] else None
    if game is not None and not game.is_absolute():
        game=(ROOT/game).resolve()
        preferences['game_dir']=str(game)
    if game is None or not game.is_dir():
        for title in SUPPORTED_TITLES:
            try:
                bundled=validate_game(ROOT/'game'/title)
            except (ValueError,OSError):
                continue
            preferences['game_dir']=str(bundled)
            break
    return preferences

def save_preferences(preferences):
    path=ROOT/'user/launcher.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    saved=dict(preferences)
    if saved.get('game_dir'):
        game=Path(saved['game_dir'])
        if game.is_absolute() and game.resolve().is_relative_to(ROOT.resolve()):
            saved['game_dir']=game.resolve().relative_to(ROOT.resolve()).as_posix()
    path.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')

def resolve_language(game,selection='auto'):
    if selection not in LANGUAGES:
        raise ValueError(f'不支持的语言选项：{selection}')
    folders={'zh-cn':'zhocn','zh-tw':'zhotw'}
    def available(language):
        directory=Path(game)/'dvdroot_ps4/msg'/folders[language]
        return all((directory/name).is_file() and (directory/name).stat().st_size>0
                   for name in ('menu.msgbnd.dcx','item.msgbnd.dcx'))
    if selection=='auto':
        selection=next((language for language in folders if available(language)),'en')
    elif selection in folders and not available(selection):
        raise ValueError(f'游戏缺少所选中文资源：dvdroot_ps4/msg/{folders[selection]}')
    return selection,LANGUAGES[selection]

def validate_game(game):
    game=Path(game).resolve()
    required=('eboot.bin','sce_sys/param.sfo','sce_module/libc.prx','sce_module/libSceFios2.prx')
    missing=[name for name in required if not (game/name).is_file() or (game/name).stat().st_size==0]
    if missing:
        raise ValueError('游戏文件不完整：'+', '.join(missing))
    if not (game/'dvdroot_ps4').is_dir():
        raise ValueError('缺少 dvdroot_ps4 游戏数据目录。')
    values=sfo((game/'sce_sys/param.sfo').read_bytes())
    if values.get('TITLE_ID') not in SUPPORTED_TITLES:
        raise ValueError(f"当前移植支持 CUSA03173、CUSA03023，当前是 {values.get('TITLE_ID')}。")
    if values.get('APP_VER') not in ('01.09','1.09'):
        raise ValueError(f"此移植需要游戏 1.09，当前是 {values.get('APP_VER')}。")
    return game

def write_profile(path,name):
    output,preset=PROFILES[name]
    return save_settings(path,{'preset':str(preset),'output_res':output,'live_resolution':'0'})

def runtime_environment():
    env=os.environ.copy()
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    candidates=[ROOT,ROOT/'dist/windows',ROOT.parent/'tools-local/msys64/ucrt64/bin',Path('C:/msys64/ucrt64/bin')]
    env['PATH']=os.pathsep.join(str(p) for p in candidates if p.is_dir())+os.pathsep+env.get('PATH','')
    # The launcher configuration also drives the offline resolution patches.
    for key in ('BB_UPSCALER','BB_UPSCALE_PRESET','BB_RENDER_RES','BB_OUTPUT_RES',
                'BB_DMEM_MB','BB_LIVE_RES','BB_FPS','BB_FPS_LIMIT','BB_VBLANK_HZ','BB_LANGUAGE','BB_FULLSCREEN','BB_FULLSCREEN_REFRESH_HZ','BB_PAD_LAYOUT','BB_PRESENT_MODE',
                'BB_CONFIG','BB_FSR_SHARPNESS','BB_JITTER','BB_REACTIVE','BB_REACTIVE_SCALE',
                'BB_REACTIVE_THRESHOLD','BB_REACTIVE_MAX','BB_OBJECT_MOTION','BB_FSR4_DIR','BB_FSR4_OPT'):
        env.pop(key,None)
    env.pop('BB_GPU_USER_DIR',None)
    return env

def renderer_path():
    for candidate in (ROOT/'bb-probe.exe',ROOT/'dist/windows/bb-probe.exe'):
        if candidate.is_file(): return candidate
    return ROOT/'out/windows/bin/bb-probe.exe'

def console_python():
    executable=Path(sys.executable)
    if executable.name.lower()=='pythonw.exe':
        # pythonw can write its redirected Python streams, but its native children
        # inherit invalid CRT standard handles. A hidden console worker keeps the
        # preparation tools and renderer attached to last-run.log as well.
        executable=executable.with_name('python.exe')
        if not executable.is_file():
            raise ValueError('缺少 python.exe；请将它与 pythonw.exe 一起保留，以便记录游戏日志。')
    return str(executable)

def start_worker(arguments,log_handle):
    child_env=runtime_environment()
    child_env.update(PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1')
    if FROZEN:
        command=[sys.executable,'--worker',*arguments]
    else:
        command=[console_python(),'-u',str(ROOT/'run_windows.py'),*arguments]
    return subprocess.Popen(command,cwd=ROOT,env=child_env,stdout=log_handle,stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

def script_command(script,*arguments):
    """准备脚本的运行命令：源码模式用解释器跑 scripts/ 下的文件；冻结模式由
    exe 自派发（--exec-module），脚本代码内嵌在 exe 里，不再有 .py 可改。"""
    arguments=[str(a) for a in arguments]
    if FROZEN:
        return [sys.executable,'--exec-module',Path(script).stem,*arguments]
    return [sys.executable,str(ROOT/'scripts'/script),*arguments]

def execute(command,env):
    subprocess.run([str(v) for v in command],cwd=ROOT,env=env,check=True)

def launch(game,resolution=None,prepare_only=False,*,language=None,fullscreen=None,controller_layout=None,fps=None,vsync=None,sync_refresh=None):
    game=validate_game(game)
    preferences=read_preferences()
    language=preferences['language'] if language is None else language
    fullscreen=preferences['fullscreen'] if fullscreen is None else fullscreen
    controller_layout=preferences['controller_layout'] if controller_layout is None else controller_layout
    fps=preferences['fps'] if fps is None else fps
    vsync=preferences['vsync'] if vsync is None else vsync
    sync_refresh=preferences['sync_refresh'] if sync_refresh is None else sync_refresh
    if fps not in FPS_CHOICES:
        raise ValueError(f'不支持的帧率选项：{fps}')
    if controller_layout not in CONTROLLER_LAYOUTS:
        raise ValueError(f'不支持的手柄按键方案：{controller_layout}')
    resolved_language,language_id=resolve_language(game,language)
    executable=renderer_path()
    if not executable.is_file() and not prepare_only:
        raise ValueError('完整 Windows 渲染器尚未构建，请运行 build_windows.ps1。诊断版本不能用于游戏。')
    data=ROOT/'out/windows-data'
    data.mkdir(parents=True,exist_ok=True)
    config=ROOT/'bbport.ini'
    if resolution: settings=write_profile(config,resolution)
    elif config.is_file(): settings=load_settings(config)
    else: settings=write_profile(config,preferences['resolution'])
    preferences.update(game_dir=str(game),resolution=resolution or preferences['resolution'],
                       language=language,fullscreen=fullscreen,controller_layout=controller_layout,fps=fps,vsync=vsync,
                       sync_refresh=sync_refresh)
    save_preferences(preferences)
    env=runtime_environment()
    smooth_60=sync_refresh and fps=='60' and fullscreen and vsync
    patch_fps='uncap' if smooth_60 else fps
    env.update(BB_LANGUAGE=str(language_id),BB_FULLSCREEN='1' if fullscreen else '0',
               BB_PAD_LAYOUT=controller_layout,BB_CONFIG=str(config),BB_FPS=patch_fps,
               BB_PRESENT_MODE='Fifo' if vsync else 'Immediate',
               BB_FSR4_DIR=str(ROOT/'fsr4_shaders'),BB_FSR4_OPT='1',
               BB_VBLANK_HZ='0' if patch_fps=='uncap' else '90' if patch_fps=='90' else '60')
    fullscreen_refresh_hz=120 if smooth_60 else None
    if smooth_60:
        env.update(BB_FPS_LIMIT='60',BB_FULLSCREEN_REFRESH_HZ=str(fullscreen_refresh_hz))
    for script in ('prepare.py','link_libc.py','link_modules.py','content_profile.py'):
        command=script_command(script,game,'--out',data)
        if script in ('link_libc.py','link_modules.py'): command+=['--target','windows']
        execute(command,env)
    sizes=scaled_sizes(settings)
    patch=script_command('patches.py','--out',data,'--fps',patch_fps,
                         '--settings',config,'--game-dir',game)
    if sizes:
        render,output=sizes
        render_text=f'{render[0]}x{render[1]}'
        output_text=f'{output[0]}x{output[1]}'
        patch+=['--render-res',render_text,'--output-res',output_text]
        env.update(BB_RENDER_RES=render_text,BB_OUTPUT_RES=output_text,BB_DMEM_MB='9152')
    else:
        for key in ('BB_RENDER_RES','BB_OUTPUT_RES','BB_DMEM_MB'): env.pop(key,None)
    execute(patch,env)
    saved=ROOT/'user'
    saved.mkdir(exist_ok=True)
    state={'game_dir':str(game),'resolution':preferences['resolution'],
           'fps':fps,'patch_fps':patch_fps,'target_fps':int(fps) if fps!='uncap' else 'display',
           'output_res':settings.get('output_res'),'upscaler':settings.get('upscaler','fsr3'),
           'language':language,'resolved_language':resolved_language,'language_id':language_id,
           'fullscreen':fullscreen,'controller_layout':controller_layout,'vsync':vsync,
           'sync_refresh':sync_refresh,'fullscreen_refresh_hz':fullscreen_refresh_hz,'gameplay_verified':False}
    (data/'launch.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    if prepare_only: return
    env.update(BB_FRAME_STATS='1',BB_FRAMES_AHEAD='2' if smooth_60 else '1',BB_LIVE_RES='0')
    args=[executable,data/'boot-linked.bin','--content-profile',data/'content.bin',
          '--patches',data/'patches.bin','--app0',game,'--user',saved,'--timeout','0']
    # Restart requests exit with 75: let the old GPU process fully release its device first.
    while True:
        code=subprocess.call([str(v) for v in args],cwd=ROOT,env=env)
        if code!=75:
            if code: raise subprocess.CalledProcessError(code,args)
            break
        return launch(game,resolution=None,language=language,fullscreen=fullscreen,controller_layout=controller_layout,fps=fps,
                      vsync=vsync,sync_refresh=sync_refresh)

def gui(game_dir=None,resolution=None,language=None,fullscreen=None,controller_layout=None,fps=None,vsync=None,sync_refresh=None):
    import tkinter as tk
    from tkinter import filedialog,messagebox,ttk
    root=tk.Tk()
    root.title('血源 · Windows 实验版')
    from windows_graphics_ui import GraphicsPanel
    root.geometry('780x620')
    root.resizable(False,False)
    outer=ttk.Frame(root,padding=20); outer.pack(fill='both',expand=True)
    tabs=ttk.Notebook(outer); tabs.pack(fill='both',expand=True)
    frame=ttk.Frame(tabs,padding=20); tabs.add(frame,text='启动')
    initial_graphics=load_settings(ROOT/'bbport.ini')
    graphics=GraphicsPanel(tabs,initial_graphics); tabs.add(graphics,text='画面设置')
    ttk.Label(frame,text='血源 · Windows 实验版',font=('Microsoft YaHei UI',18)).pack(anchor='w')
    ttk.Label(frame,text='支持 CUSA03173 / CUSA03023 的 1.09 已解密数据。').pack(anchor='w',pady=(12,16))
    preferences=read_preferences()
    game=tk.StringVar(value=str(game_dir) if game_dir else preferences['game_dir'])
    row=ttk.Frame(frame); row.pack(fill='x')
    ttk.Entry(row,textvariable=game).pack(side='left',fill='x',expand=True)
    def pick():
        selected=filedialog.askdirectory(title='选择含 eboot.bin 的血源 1.09 游戏文件夹')
        if selected: game.set(selected)
    ttk.Button(row,text='选择文件夹',command=pick).pack(side='right',padx=(8,0))
    labels={'720p · 1280×720':'1280x720','1080p · 1920×1080':'1920x1080',
            '1440p · 2560×1440':'2560x1440','4K · 3840×2160':'3840x2160'}
    profile=resolution or preferences['resolution']
    output=PROFILES[profile][0] if resolution or not (ROOT/'bbport.ini').exists() else initial_graphics['output_res']
    chosen=tk.StringVar(value=next(label for label,value in labels.items() if value==output))
    ttk.Combobox(frame,textvariable=chosen,values=list(labels),state='readonly',width=36).pack(anchor='w',pady=16)
    if resolution or not (ROOT/'bbport.ini').exists():
        output,preset=PROFILES[profile]; graphics.set_profile(output,str(preset))
    def update_profile(*_):
        graphics.set_profile(labels[chosen.get()],graphics.values()['preset'])
    chosen.trace_add('write',update_profile)
    fps_options=ttk.Frame(frame); fps_options.pack(fill='x',pady=(0,12))
    ttk.Label(fps_options,text='游戏帧率：').pack(side='left')
    selected_fps=preferences['fps'] if fps is None else fps
    chosen_fps=tk.StringVar(value=next(label for label,value in FPS_LABELS.items() if value==selected_fps))
    ttk.Combobox(fps_options,textvariable=chosen_fps,values=list(FPS_LABELS),state='readonly',width=34).pack(side='left')
    options=ttk.Frame(frame); options.pack(fill='x',pady=(0,12))
    ttk.Label(options,text='游戏语言：').pack(side='left')
    selection=preferences['language'] if language is None else language
    chosen_language=tk.StringVar(value=next(label for label,value in LANGUAGE_LABELS.items() if value==selection))
    ttk.Combobox(options,textvariable=chosen_language,values=list(LANGUAGE_LABELS),
                 state='readonly',width=20).pack(side='left')
    chosen_fullscreen=tk.BooleanVar(value=preferences['fullscreen'] if fullscreen is None else fullscreen)
    ttk.Checkbutton(options,text='全屏运行',variable=chosen_fullscreen).pack(side='left',padx=(20,0))
    chosen_vsync=tk.BooleanVar(value=preferences['vsync'] if vsync is None else vsync)
    ttk.Checkbutton(options,text='垂直同步',variable=chosen_vsync).pack(side='left',padx=(20,0))
    chosen_sync_refresh=tk.BooleanVar(value=preferences['sync_refresh'] if sync_refresh is None else sync_refresh)
    ttk.Checkbutton(frame,text='平稳 60 帧（120 Hz 全屏）',variable=chosen_sync_refresh).pack(anchor='w',pady=(0,12))
    controller_options=ttk.Frame(frame); controller_options.pack(fill='x',pady=(0,8))
    ttk.Label(controller_options,text='手柄按键：').pack(side='left')
    layout=preferences['controller_layout'] if controller_layout is None else controller_layout
    chosen_swap_ab=tk.BooleanVar(value=CONTROLLER_SWAPS[layout][0])
    chosen_swap_xy=tk.BooleanVar(value=CONTROLLER_SWAPS[layout][1])
    ttk.Checkbutton(controller_options,text='A/B 互换',variable=chosen_swap_ab).pack(side='left')
    ttk.Checkbutton(controller_options,text='X/Y 互换',variable=chosen_swap_xy).pack(side='left',padx=(20,0))
    def chosen_controller_layout():
        swaps=(chosen_swap_ab.get(),chosen_swap_xy.get())
        return next(name for name,pair in CONTROLLER_SWAPS.items() if pair==swaps)
    controller_hint=tk.StringVar(value=CONTROLLER_HINTS[layout])
    def update_controller_hint(*_):
        controller_hint.set(CONTROLLER_HINTS[chosen_controller_layout()])
    chosen_swap_ab.trace_add('write',update_controller_hint)
    chosen_swap_xy.trace_add('write',update_controller_hint)
    ttk.Label(frame,textvariable=controller_hint).pack(anchor='w',pady=(0,12))
    ttk.Label(frame,text='“画面设置”可调整 FSR、抗锯齿和游戏特效。').pack(anchor='w')
    ttk.Label(frame,text='30 帧使用原版时序；90 帧与高刷新率为实验选项。').pack(anchor='w',pady=(8,0))
    status=tk.StringVar(value='请选择已解密游戏文件夹。')
    ttk.Label(outer,textvariable=status,wraplength=710).pack(anchor='w',pady=(12,0))
    process=None
    log_handle=None
    def save_choices():
        output=labels[chosen.get()]
        profile={'1280x720':'1080p','1920x1080':'1080p','2560x1440':'1440p','3840x2160':'4k'}[output]
        preferences.update(game_dir=game.get(),resolution=profile,
                           language=LANGUAGE_LABELS[chosen_language.get()],fullscreen=chosen_fullscreen.get(),
                           controller_layout=chosen_controller_layout(),fps=FPS_LABELS[chosen_fps.get()],
                           vsync=chosen_vsync.get(),sync_refresh=chosen_sync_refresh.get())
        graphics.values() # validate every field before saving any changes
        changes=graphics.changes()
        if changes: save_settings(ROOT/'bbport.ini',changes)
        save_preferences(preferences)
        graphics.mark_saved()
    def save_only():
        try:
            save_choices(); status.set('设置已保存，下次启动游戏时生效。')
        except (ValueError,OSError) as error: messagebox.showerror('无法保存设置',str(error))
    def close():
        try: save_choices()
        except (ValueError,OSError) as error:
            messagebox.showerror('无法保存设置',str(error))
            return
        root.destroy()
    root.protocol('WM_DELETE_WINDOW',close)
    def monitor():
        nonlocal process,log_handle
        code=process.poll()
        if code is None:
            root.after(500,monitor)
            return
        log_handle.close(); log_handle=None; process=None
        start_button.configure(state='normal')
        status.set('游戏已退出。' if code==0 else '启动失败，日志已保存到 out/windows-data/last-run.log。')
        if code:
            messagebox.showerror('运行失败',f'退出码：{code}\n请查看 {ROOT / "out/windows-data/last-run.log"}')
    def start():
        nonlocal process,log_handle
        try:
            validate_game(game.get())
            resolve_language(game.get(),LANGUAGE_LABELS[chosen_language.get()])
            if not renderer_path().is_file(): raise ValueError('缺少完整 Windows 程序，请先运行 build_windows.ps1。')
            save_choices()
            log_path=ROOT/'out/windows-data/last-run.log'
            log_path.parent.mkdir(parents=True,exist_ok=True)
            log_handle=log_path.open('w',encoding='utf-8')
            process=start_worker(['--game',game.get(),
                              '--language',LANGUAGE_LABELS[chosen_language.get()],
                              '--fps',FPS_LABELS[chosen_fps.get()],
                              '--controller-layout',chosen_controller_layout(),
                              '--vsync' if chosen_vsync.get() else '--no-vsync',
                              '--sync-refresh' if chosen_sync_refresh.get() else '--no-sync-refresh',
                              '--fullscreen' if chosen_fullscreen.get() else '--windowed'],log_handle)
            start_button.configure(state='disabled'); status.set('正在准备或运行；日志实时保存在 out/windows-data/last-run.log。')
            root.after(500,monitor)
        except (ValueError,OSError) as error:
            if log_handle: log_handle.close(); log_handle=None
            messagebox.showerror('无法启动',str(error))
    buttons=ttk.Frame(outer); buttons.pack(fill='x',pady=(12,0))
    ttk.Button(buttons,text='保存设置',command=save_only).pack(side='left')
    start_button=ttk.Button(buttons,text='启动游戏',command=start)
    start_button.pack(side='right')
    root.mainloop()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',type=Path)
    parser.add_argument('--resolution',choices=PROFILES)
    parser.add_argument('--fps',choices=FPS_CHOICES,help='30、60、90 帧或跟随显示器（最高 120 帧）；省略时沿用已保存的选择。')
    parser.add_argument('--language',choices=LANGUAGES,help='游戏语言；自动优先使用已有简体、繁体中文资源。')
    parser.add_argument('--controller-layout',choices=CONTROLLER_LAYOUTS,
                        help='手柄按键：ps4 原版，swap-ab 仅 A/B 互换，swap-xy 仅 X/Y 互换，xbox 两组互换；省略时沿用已保存的设置。')
    display=parser.add_mutually_exclusive_group()
    display.add_argument('--fullscreen',dest='fullscreen',action='store_true',default=None,
                         help='全屏运行。省略时沿用已保存的设置。')
    display.add_argument('--windowed','--no-fullscreen',dest='fullscreen',action='store_false',
                         help='窗口运行。省略时沿用已保存的设置。')
    sync=parser.add_mutually_exclusive_group()
    sync.add_argument('--vsync',dest='vsync',action='store_true',default=None,
                      help='开启垂直同步；省略时沿用已保存的设置。')
    sync.add_argument('--no-vsync',dest='vsync',action='store_false',
                      help='关闭垂直同步；省略时沿用已保存的设置。')
    refresh=parser.add_mutually_exclusive_group()
    refresh.add_argument('--sync-refresh',dest='sync_refresh',action='store_true',default=None,
                         help='60 帧、全屏且开启垂直同步时使用动态时序、60 帧限制和 120 Hz；省略时沿用已保存的设置。')
    refresh.add_argument('--no-sync-refresh',dest='sync_refresh',action='store_false',
                         help='沿用显示器当前刷新率；省略时沿用已保存的设置。')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--gui',action='store_true')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.gui: gui(args.game,args.resolution,args.language,args.fullscreen,args.controller_layout,args.fps,args.vsync,args.sync_refresh); return 0
    if args.game is None:
        saved_game=read_preferences()['game_dir']
        if saved_game: args.game=Path(saved_game)
    if args.check:
        print(json.dumps({'windows':os.name=='nt','renderer_built':renderer_path().is_file(),
                          'game_dir':str(args.game) if args.game else None,'target_fps':60,
                          'profiles':list(PROFILES),'languages':list(LANGUAGES),
                          'controller_layouts':list(CONTROLLER_LAYOUTS),'frame_rates':list(FPS_CHOICES),
                          'gameplay_verified':False},ensure_ascii=False,indent=2))
        if args.game: validate_game(args.game)
        return 0
    if not args.game: parser.error('请指定 --game 游戏目录，或使用 --gui。')
    launch(args.game,args.resolution,args.prepare_only,language=args.language,fullscreen=args.fullscreen,
           controller_layout=args.controller_layout,fps=args.fps,vsync=args.vsync,sync_refresh=args.sync_refresh)
    return 0

def _frozen_console():
    # PyInstaller 的 windowed 模式没有 Python 标准流；worker 的日志句柄由父进程
    # 接在 stdout 上，这里接回该句柄（失败则丢弃输出），避免 print 崩溃。
    # 子进程继承的仍是有效的 OS 句柄。
    if sys.stdout is not None and sys.stderr is not None: return
    sink=None
    try:
        sink=open(os.dup(1),'w',encoding='utf-8',errors='replace',buffering=1)
    except OSError:
        pass
    if sys.stdout is None: sys.stdout=sink or open(os.devnull,'w',encoding='utf-8')
    if sys.stderr is None: sys.stderr=sink or sys.stdout

def run():
    if FROZEN:
        _frozen_console()
        # 双击（无参数）等价于源码模式的 start_windows.cmd：直接打开 GUI。
        if len(sys.argv)==1:
            sys.argv.append('--gui')
        arguments=sys.argv[1:]
        if arguments[:1]==['--worker']:
            del sys.argv[1]
        elif arguments[:1]==['--exec-module'] and len(arguments)>1:
            import runpy
            module,module_arguments=arguments[1],arguments[2:]
            sys.argv=[module,*module_arguments]
            try:
                runpy.run_module(module,run_name='__main__',alter_sys=True)
            except SystemExit as exit_code:
                return int(exit_code.code or 0)
            return 0
    try: return main()
    except subprocess.CalledProcessError as error:
        print(f'运行失败：{error}',file=sys.stderr)
        return error.returncode
    except (ValueError,OSError) as error:
        print(f'无法启动：{error}',file=sys.stderr)
        return 1

if __name__=='__main__': sys.exit(run())
