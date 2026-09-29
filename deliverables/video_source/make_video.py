"""Reproducible narrated 1080p demo. Requires Pillow, FFmpeg, project edge_tts.
Run: python deliverables/video_source/make_video.py --prepare
Then: python deliverables/video_source/make_video.py --render
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, json, math, re, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "deliverables"
ASSETS = OUT / "video_assets"
WORK = ROOT / "tmp" / "video"
SOURCE = OUT / "video_source"
FINAL = OUT / "智驾未来_AI面试仓_命题05演示.mp4"
TTS_PY = ROOT / ".venv" / "Scripts" / "python.exe"
W, H, FPS = 1920, 1080, 25
BG, PANEL, INK, MUTED = "#07131e", "#102434", "#eef8ff", "#a7bccb"
CYAN, ORANGE, LINE = "#65e1e7", "#ffb477", "#244253"
FONT = "C:/Windows/Fonts/msyh.ttc"
BOLD = "C:/Windows/Fonts/msyhbd.ttc"

SCENES = [
 dict(key="opening",chapter="01 / 项目定位",title="智驾未来\nAI 面试仓",lead="让每一次训练，\n都有下一步。",labels=["岗位定向","可解释评分","三端闭环"],image=None,diagram="triple",voice="面向智能汽车产业，智驾未来 AI 面试仓，把岗位认知、面试训练和企业初筛连接起来。围绕命题零五，我们将一次面试，变成可以解释、复盘和再次训练的学习过程。"),
 dict(key="jobs",chapter="02 / 岗位准备",title="两个种子岗位\n做深专业训练",lead="智驾测试 · 三电系统测试\n岗位术语与 JD 要点进入题目语境。",labels=["固定 2 题","专业 3 题","情景 1 题"],image="jobs.png",diagram="jobs",voice="学生先选择目标岗位。项目聚焦智驾测试和三电系统测试两个种子岗位，用岗位术语和 JD 要点组织题库。六道主问题覆盖基础表达、专业知识和工作情景。"),
 dict(key="interview",chapter="03 / 面试过程",title="听题、回答\n逐步完成训练",lead="语音提问与回答转写\n题目进度由服务端保存。",labels=["语音输入","文本备用","每题最多一次追问"],image="interview.png",diagram="flow",voice="进入面试后，系统朗读问题，学生通过语音回答，也可以使用文本模式。服务端保存面试状态，每道题最多追问一次；追问服务失败时，直接进入下一题。"),
 dict(key="acoustic",chapter="04 / 表达量化",title="把表达习惯\n变成可读指标",lead="同一份真实报告中的声学观测\n语速、停顿与填充词共同提供依据。",labels=["178 字 / 分","2.3 次停顿 / 分","2.6 次填充词 / 分"],image="report_acoustic.png",diagram="acoustic",voice="语音训练记录语速、停顿和填充词。这份报告显示，语速为每分钟一百七十八字，停顿二点三次，填充词二点六次。量化值帮助解释表达习惯，不能替代专业能力判断。"),
 dict(key="report",chapter="05 / 可解释报告",title="评分之后\n看得见依据",lead="真实会话 #6 · 报告 #4\n综合评定 79.2 分。",labels=["四维评估","原话证据","具体改进建议"],image="report.png",diagram="report",voice="训练完成后，报告用四个维度呈现表现。这是会话六的真实报告，综合评定七十九点二分。分数旁边保留原话依据、原因和改进建议，帮助学生理解为什么，以及下一步怎么练。"),
 dict(key="evidence",chapter="06 / 公平与边界",title="有证据才评价\n缺失就不补分",lead="文本训练不评估语音流畅度\n缺失维度显示“未评估”。",labels=["两次独立评分","引用原回答","有效维度计算均值"],image="report_evidence.png",diagram="evidence",voice="评分按两次独立调用汇总，并校验引用是否来自原回答。文本训练没有真实声学信息，表达流畅度就显示未评估；缺失维度不会填成零分，也不会凭空生成语音表现。"),
 dict(key="growth",chapter="07 / 训练复盘",title="记录真实变化\n不虚构成长",lead="同一学生 · 同一岗位 · 可比口径\n历史报告与建议可以回看。",labels=["当前只有一次记录","不计算增减","支持再次训练"],image="growth.png",diagram="growth",voice="成长记录按学生和岗位隔离，只比较口径一致、同时有效的维度。本次演示只有一条训练记录，所以页面明确提示暂时无法比较。系统保留历史报告和建议，支持下一次训练。"),
 dict(key="learning",chapter="08 / 新生学习",title="先学会表达\n再写自己的答案",lead="识别 → 诊断 → 搭建 → 练习\n理解题意，组织真实经历。",labels=["STAR 经历题","诚实说明不会","按报告复盘"],image="learn.png",diagram="learning",voice="新生可以进入面试学习菜单，从识别题意、诊断问题，到搭建结构，再写自己的答案。经历题学习 STAR，知识题不生搬硬套；也练习澄清问题和诚实说明不会的内容。"),
 dict(key="counsel",chapter="09 / 岗位认知",title="从专业兴趣\n走向岗位路径",lead="输入专业、年级与兴趣\n查看岗位地图、能力差距和学习路径。",labels=["不生成咨询分数","可进入岗位训练","静态建议持续可用"],image="counsel.png",diagram="counsel",voice="新生输入专业、年级和兴趣，可以查看岗位地图、能力差距和学习路径。本次咨询触发了静态回退，页面仍然提供可用建议。咨询本身不会虚构面试分数。"),
 dict(key="enterprise",chapter="10 / 企业初筛",title="候选排序\n回到同源证据",lead="同岗位 · 每位学生一条候选记录\n可追溯至原始会话和报告。",labels=["岗位权重","分评分口径","缺维不按零分处罚"],image="recruiter.png",diagram="enterprise",voice="企业端围绕岗位需求组织评估维度和题库。候选记录来自学生端已经落库的会话和报告，同一岗位每位学生保留一条符合要求的候选记录，并区分评分口径，支持回看原始证据。"),
 dict(key="architecture",chapter="11 / 技术支撑",title="关键能力\n落在可运行链路",lead="Next.js / FastAPI / SQLite\n本地语音识别 + 模型分级回退。",labels=["岗位知识注入","声学特征量化","原话证据校验"],image=None,diagram="architecture",voice="前端负责交互，后端统一编排、评分和数据保存。本地语音识别配合语音合成，模型按旗舰、普通云端和本地模型分级回退，让关键功能在服务波动时保持可用。"),
 dict(key="closing",chapter="12 / 命题回应",title="从一次回答\n到下一次进步",lead="学生训练有反馈\n新生学习有方向\n企业初筛有依据",labels=["本机 / 局域网运行","真实记录","可解释反馈"],image=None,diagram="triple",voice="岗位定向题库、声学量化和原话证据，是项目的三个创新支点。我们面向本机和局域网应用，让学生训练有反馈，新生学习有方向，企业初筛有依据。智驾未来，AI 面试仓。"),
]

def run(args,**kwargs):
 result=subprocess.run([str(x) for x in args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs)
 if result.returncode: raise RuntimeError(result.stderr.decode("utf-8","replace")[-5000:])
 return result.stdout

def duration(path):
 return float(run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",path]))

def font(size,bold=False): return ImageFont.truetype(BOLD if bold else FONT,size)

def write(d,xy,text,size,fill=INK,bold=False,width=None,spacing=15):
 x,y=xy; f=font(size,bold); lines=[]
 for para in text.split("\n"):
  line=""
  for ch in para:
   if width and d.textlength(line+ch,font=f)>width and line: lines.append(line);line=ch
   else: line+=ch
  lines.append(line)
 for line in lines: d.text((x,y),line,font=f,fill=fill);y+=size+spacing
 return y

def pill(d,xy,text,size=25,fill=CYAN):
 x,y=xy;tw=int(d.textlength(text,font=font(size)))
 d.rounded_rectangle((x,y,x+tw+42,y+53),radius=26,fill="#132d3b",outline=LINE,width=1)
 write(d,(x+21,y+8),text,size,fill)

def card(d,rect,title,body,accent=CYAN):
 x,y,r,b=rect
 d.rounded_rectangle(rect,radius=22,fill=PANEL,outline=LINE,width=2)
 d.rounded_rectangle((x+24,y+27,x+30,b-26),radius=3,fill=accent)
 write(d,(x+54,y+24),title,34,INK,True,width=r-x-80)
 write(d,(x+54,y+88),body,25,MUTED,width=r-x-80,spacing=11)

def render_diagram(d,kind):
 x,y=1090,177;right=1800
 write(d,(x,127),"功能示意" if kind=="enterprise" else "机制示意",24,ORANGE if kind=="enterprise" else CYAN)
 data={
 "triple":[("01  新生","理解岗位  /  规划学习"),("02  学生","真实训练  /  反馈复盘"),("03  企业","同源报告  /  核对依据")],
 "architecture":[("交互层","Next.js · 语音输入 · 报告展示"),("服务层","FastAPI · 编排 · 评分 · 反馈"),("基础层","SQLite · 本地 ASR · TTS · LLM")],
 "enterprise":[("学生会话","训练完成并生成真实报告"),("资格筛选","同岗位 · 同学生 · 可比口径"),("候选记录","加权排序 → 回看原报告")],
 "acoustic":[("178 字 / 分","语速 · 观测值"),("2.3 次 / 分","停顿频率 · 观测值"),("2.6 次 / 分","填充词频率 · 观测值")],
 "evidence":[("01  引用","证据来自本场原始回答"),("02  校验","缺失信息保持 null"),("03  反馈","有效维度形成可解释建议")],
 "jobs":[("智驾测试","专业术语与岗位要求"),("三电系统测试","真实工作情景"),("6 道主问题","固定 2 + 专业 3 + 情景 1")],
 "flow":[("01  朗读问题","TTS 提问与进度显示"),("02  提交回答","音频转写或文本输入"),("03  继续训练","追问 / 下一题 / 生成报告")]}
 for i,(title,body) in enumerate(data.get(kind,data["triple"])):
  card(d,(x,y+i*228,right,y+185+i*228),title,body,CYAN if i!=2 else ORANGE)
  if i<2:d.line((x+354,y+193+i*228,x+354,y+217+i*228),fill=CYAN,width=3)

def render_scene(scene,idx):
 im=Image.new("RGB",(W,H),BG);d=ImageDraw.Draw(im)
 for yy in range(H):
  t=yy/H;d.line((0,yy,W,yy),fill=(7+int(3*t),19+int(8*t),30+int(12*t)))
 for xx in range(1000,W,80):d.line((xx,110,xx-310,929),fill="#102634",width=1)
 d.line((78,100,1842,100),fill=LINE,width=2)
 d.rounded_rectangle((78,43,93,68),radius=4,fill=CYAN)
 write(d,(110,37),"智驾未来  /  AI 面试仓",27,INK,True)
 write(d,(1378,41),"实页讲解 · 2026.09.29",25,MUTED)
 write(d,(80,144),scene["chapter"],28,CYAN)
 bottom=write(d,(75,215),scene["title"],76,INK,True,width=960,spacing=26)
 bottom=write(d,(80,bottom+37),scene["lead"],33,MUTED,width=900,spacing=21)
 for i,label in enumerate(scene["labels"]):pill(d,(80,min(max(bottom+30,654),672)+i*69),label,25,ORANGE if i==2 else CYAN)
 path=ASSETS/scene["image"] if scene.get("image") else None
 if path and path.exists():
  src=Image.open(path).convert("RGB")
  # Authorized editorial crop: remove the bottom 80 px browser-dev/account overlay.
  src=src.crop((0,0,src.width,max(1,src.height-80)))
  src.thumbnail((676,747),Image.Resampling.LANCZOS)
  sx=1447-src.width//2;sy=158+(747-src.height)//2
  d.rounded_rectangle((sx-17,sy-17,sx+src.width+17,sy+src.height+17),radius=30,fill="#142c3c",outline="#456173",width=2)
  im.paste(src,(sx,sy));write(d,(1096,119),"实页截图",22,CYAN)
  scene["visual_type"]="real_page_screenshot";scene["image_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
 else:render_diagram(d,scene["diagram"]);scene["visual_type"]="labeled_mechanism_illustration"
 d.rounded_rectangle((58,942,1862,1036),radius=24,fill="#030c15",outline=LINE,width=1)
 write(d,(81,902),f"{idx+1:02d} / {len(SCENES):02d}",20,MUTED)
 d.line((222,918,992,918),fill=LINE,width=3)
 d.line((222,918,222+round(770*(idx+1)/len(SCENES)),918),fill=CYAN,width=3)
 dest=WORK/f"{idx:02d}_{scene['key']}.png";im.save(dest);return dest

def tts_one(pair):
 idx,scene=pair;target=ASSETS/f"narration_{idx:02d}.mp3";txt=SOURCE/f"narration_{idx:02d}.txt"
 txt.write_text(scene["voice"],encoding="utf-8")
 fingerprint=hashlib.sha256((scene["voice"]+"zh-CN-YunxiNeural+15%").encode()).hexdigest();marker=ASSETS/f"narration_{idx:02d}.sha256"
 if not target.exists() or not marker.exists() or marker.read_text()!=fingerprint:
  run([TTS_PY,"-m","edge_tts","--voice","zh-CN-YunxiNeural","--rate=+15%","--file",txt,"--write-media",target],timeout=150)
  marker.write_text(fingerprint)
 scene["audio"]=str(target.relative_to(ROOT)).replace("\\","/")
 scene["speech_duration"]=duration(target);scene["duration"]=math.ceil((scene["speech_duration"]+1.3)*FPS)/FPS
 print(f"Narration {idx+1:02d}: {scene['speech_duration']:.2f}s",flush=True)

def subtitle_parts(text):
 phrases=re.findall(r"[^，。；！？]+[，。；！？]?",text);pieces=[];current=""
 for phrase in phrases:
  if len(current+phrase)>29 and current:pieces.append(current.rstrip("，。；"));current=""
  if len(phrase)>29:
   if current:pieces.append(current.rstrip("，。；"));current=""
   for at in range(0,len(phrase),29):pieces.append(phrase[at:at+29].rstrip("，。；"))
  else:current+=phrase
 if current:pieces.append(current.rstrip("，。；"))
 return pieces

def stamp(seconds,ass=False):
 if ass:
  c=round(seconds*100);return f"{c//360000}:{c//6000%60:02}:{c//100%60:02}.{c%100:02}"
 m=round(seconds*1000);return f"{m//3600000:02}:{m//60000%60:02}:{m//1000%60:02},{m%1000:03}"

def subtitles(scenes):
 srt=[];events=[];offset=0;index=1
 for scene in scenes:
  chunks=subtitle_parts(scene["voice"]);total=sum(len(x) for x in chunks);at=offset+.4
  for chunk in chunks:
   end=at+scene["speech_duration"]*len(chunk)/total
   srt.append(f"{index}\n{stamp(at)} --> {stamp(end)}\n{chunk}\n")
   events.append(f"Dialogue: 0,{stamp(at,True)},{stamp(end,True)},Default,,0,0,0,,{chunk}")
   at=end;index+=1
  scene["start"]=offset;offset+=scene["duration"]
 (SOURCE/"智驾未来_演示字幕.srt").write_text("\n".join(srt),encoding="utf-8-sig")
 header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,38,&H00F8FAFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,2,110,110,61,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
 (WORK/"captions.ass").write_text(header+"\n".join(events)+"\n",encoding="utf-8")
 (SOURCE/"storyboard.json").write_text(json.dumps(dict(width=W,height=H,fps=FPS,voice="zh-CN-YunxiNeural",date="2026-09-29",duration=offset,scenes=scenes),ensure_ascii=False,indent=2),encoding="utf-8")
 return offset

def render_clip(pair):
 idx,scene=pair;frame=render_scene(scene,idx);target=WORK/f"clip_{idx:02d}.mp4";t=scene["duration"]
 vf=f"fade=t=in:st=0:d=0.28,fade=t=out:st={t-.28:.2f}:d=0.28"
 run(["ffmpeg","-hide_banner","-loglevel","error","-y","-loop","1","-framerate",FPS,"-i",frame,"-i",ROOT/scene["audio"],"-vf",vf,"-af","adelay=400|400,apad,loudnorm=I=-16:TP=-1.5:LRA=9","-t",t,"-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p","-r",FPS,"-c:a","aac","-b:a","160k","-ar","48000","-movflags","+faststart",target])
 print(f"Rendered {idx+1:02d}: {target.name}",flush=True);return target

def main():
 p=argparse.ArgumentParser();p.add_argument("--prepare",action="store_true");p.add_argument("--render",action="store_true");p.add_argument("--frames-only",action="store_true");p.add_argument("--rerender",type=int,help="Regenerate one zero-based scene, then reassemble existing clips");args=p.parse_args()
 WORK.mkdir(parents=True,exist_ok=True);ASSETS.mkdir(parents=True,exist_ok=True)
 if args.frames_only:
  for idx,scene in enumerate(SCENES):render_scene(scene,idx)
  print("Frames prepared");return
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(tts_one,enumerate(SCENES)))
 total=subtitles(SCENES);print(f"Total duration: {total:.2f}s",flush=True)
 if args.prepare and not args.render:return
 if args.rerender is not None:
  for idx,scene in enumerate(SCENES):render_scene(scene,idx)
  render_clip((args.rerender,SCENES[args.rerender]))
  clips=[WORK/f"clip_{idx:02d}.mp4" for idx in range(len(SCENES))]
 else:
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:clips=list(pool.map(render_clip,enumerate(SCENES)))
 subtitles(SCENES);concat=WORK/"concat.txt"
 concat.write_text("\n".join("file '"+str(x).replace("\\","/")+"'" for x in clips),encoding="utf-8")
 assembled=WORK/"assembled.mp4"
 run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i",concat,"-c","copy",assembled])
 run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",assembled,"-vf","ass=captions.ass","-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p","-r",FPS,"-c:a","copy","-movflags","+faststart",FINAL],cwd=WORK)
 probe=json.loads(run(["ffprobe","-v","error","-show_format","-show_streams","-of","json",FINAL]))
 (SOURCE/"video_probe.json").write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding="utf-8")
 print(f"DONE: {FINAL} ({FINAL.stat().st_size/1024/1024:.2f} MiB)",flush=True)

if __name__=="__main__":main()
