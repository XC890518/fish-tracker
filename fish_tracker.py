import csv
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk
from scipy import ndimage

CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
RESAMPLE = Image.Resampling.LANCZOS


def run_command(args):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          check=True, creationflags=CREATE_NO_WINDOW).stdout


def metadata(path):
    data = json.loads(run_command(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,avg_frame_rate,duration,nb_frames:format=duration',
        '-of', 'json', str(path)]))
    stream = data['streams'][0]
    a, b = map(int, stream['avg_frame_rate'].split('/'))
    fps = a / b
    duration = float(stream.get('duration') or data['format']['duration'])
    if not fps or not duration:
        raise ValueError('影片沒有可用的影格率或長度資訊')
    return int(stream['width']), int(stream['height']), fps, duration


def grab_image(path, seconds, width, height):
    raw = run_command(['ffmpeg', '-v', 'error', '-ss', str(seconds), '-i', str(path),
                       '-frames:v', '1', '-vf', f'scale={width}:{height}',
                       '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
    if len(raw) != width * height * 3:
        raise ValueError('無法讀取影片畫面')
    return Image.frombytes('RGB', (width, height), raw)


def scaled_size(w, h):
    scale = min(1.0, 640 / w)
    return max(2, round(w * scale)), max(2, round(h * scale))


def filter_string(roi, size):
    x, y, w, h = roi
    sw, sh = size
    return f'crop={w}:{h}:{x}:{y},scale={sw}:{sh},format=gray'


def make_background(path, duration, roi, size, report, cancel):
    # Evenly spaced frames suppress a moving fish while retaining fixed marks.
    frames = []
    def sample(t):
        if cancel.is_set(): return None
        raw = run_command(['ffmpeg', '-v', 'error', '-ss', str(float(t)), '-i', str(path),
             '-frames:v', '1', '-vf', filter_string(roi, size), '-f', 'rawvideo', '-pix_fmt', 'gray', '-'])
        return np.frombuffer(raw, dtype=np.uint8).reshape(size[1], size[0]) if len(raw) == size[0] * size[1] else None
    with ThreadPoolExecutor(max_workers=3) as executor:
        for i, frame in enumerate(executor.map(sample, np.linspace(0, max(0, duration - 0.2), 21))):
            if cancel.is_set(): raise InterruptedError()
            if frame is not None: frames.append(frame)
            report(f'建立背景：{i + 1}/21')
    if len(frames) < 3:
        raise ValueError('無法取得足夠的背景畫面')
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def detect(frame, background, threshold, min_area, max_area, previous, region_mask=None):
    # Only dark departures are considered; the fixed median background removes tank marks.
    diff = background.astype(np.int16) - frame.astype(np.int16)
    mask = diff >= threshold
    if region_mask is not None:
        mask &= region_mask
    mask = ndimage.binary_opening(mask, structure=np.ones((2, 2)))
    labels, count = ndimage.label(mask)
    if not count:
        return None
    objects = ndimage.find_objects(labels)
    candidates = []
    for label, box in enumerate(objects, 1):
        if box is None:
            continue
        local = labels[box] == label
        area = int(local.sum())
        if not min_area <= area <= max_area:
            continue
        yy, xx = np.nonzero(local)
        x = float(xx.mean() + box[1].start)
        y = float(yy.mean() + box[0].start)
        strength = float(diff[box][local].mean())
        # Prefer substantial, dark blobs, with a gentle continuity preference.
        score = math.sqrt(area) * strength
        if previous is not None:
            distance = math.hypot(x - previous[0], y - previous[1])
            score /= 1 + distance / 80
        candidates.append((score, x, y, area))
    if not candidates:
        return None
    _, x, y, area = max(candidates)
    return x, y, area


def read_frame(stream, length):
    data = bytearray()
    while len(data) < length:
        chunk = stream.read(length - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return data


def valid_polygon(points):
    cross = []
    for i in range(4):
        a,b,c = points[i], points[(i+1)%4], points[(i+2)%4]
        cross.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
    return all(v > 100 for v in cross) or all(v < -100 for v in cross)


def annotated_frame(data, video_size, original_size, roi, split, row, font, polygon=None):
    image = Image.frombytes('RGB', video_size, bytes(data))
    draw = ImageDraw.Draw(image)
    sx, sy = video_size[0] / original_size[0], video_size[1] / original_size[1]
    x, y, w, h = roi
    points = polygon or [(x,y), (x+w,y), (x+w,y+h), (x,y+h)]
    coords = [(round(px*sx), round(py*sy)) for px,py in points]
    draw.line(coords + [coords[0]], fill='#00ff00', width=3)
    draw.line((round(x*sx), round(split*sy), round((x+w)*sx), round(split*sy)), fill='#ffff00', width=3)
    if row[7] == 'detected':
        px, py = round(row[2]*sx), round(row[3]*sy)
        draw.ellipse((px-9, py-9, px+9, py+9), outline='#ff2020', width=3)
        draw.line((px-13, py, px+13, py), fill='#ff2020', width=2)
        draw.line((px, py-13, px, py+13), fill='#ff2020', width=2)
        label = f'{row[1]:.2f} s | {row[6].upper()} | x={row[2]:.0f} y={row[3]:.0f}'
    else:
        label = f'{row[1]:.2f} s | MISSING'
    box = draw.textbbox((0, 0), label, font=font)
    draw.rectangle((5, 5, box[2]+17, box[3]+17), fill='black')
    draw.text((11, 8), label, fill='white', font=font)
    return image.tobytes()


def track(path, roi, split, step, threshold, min_area, max_area, output, report, cancel, max_frames=None, polygon=None, make_video=True):
    output = Path(output)
    if output.with_name(output.stem + '_tracked.mp4').resolve() == Path(path).resolve():
        raise ValueError('追蹤影片的輸出名稱與原影片相同，請更改 CSV 檔名。')
    with tempfile.TemporaryDirectory(prefix='fish_tracker_', dir=output.parent) as tempdir:
        return _track(path, roi, split, step, threshold, min_area, max_area, output, report,
                      cancel, Path(tempdir) / 'video.mp4', max_frames, polygon, make_video)


def _track(path, roi, split, step, threshold, min_area, max_area, output, report, cancel, temporary_video, max_frames, polygon, make_video):
    width, height, fps, duration = metadata(path)
    x0, y0, rw, rh = roi
    size = scaled_size(rw, rh)
    polygon = polygon or [(x0,y0),(x0+rw,y0),(x0+rw,y0+rh),(x0,y0+rh)]
    mask_image = Image.new('1', size)
    ImageDraw.Draw(mask_image).polygon([((x-x0)*size[0]/rw,(y-y0)*size[1]/rh) for x,y in polygon], fill=1)
    region_mask = np.asarray(mask_image, dtype=bool)
    background = make_background(path, duration, roi, size, report, cancel)
    # Decode sequentially: select the original frame number, keeping a clear time base.
    filt = f"select=not(mod(n\\,{step})),{filter_string(roi, size)}"
    command = ['ffmpeg', '-v', 'error', '-i', str(path), '-vf', filt, '-vsync', '0',
               '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    video_scale = min(1.0, 1280 / width)
    vw = max(2, round(width * video_scale / 2) * 2)
    vh = max(2, round(height * video_scale / 2) * 2)
    video_size = (vw, vh)
    video_filter = f'select=not(mod(n\\,{step})),scale={vw}:{vh}'
    video_command = ['ffmpeg', '-v', 'error', '-i', str(path), '-vf', video_filter,
                     '-vsync', '0', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    encode_command = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                      '-s', f'{vw}x{vh}', '-r', str(fps / step), '-i', '-', '-an',
                      '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p',
                      '-movflags', '+faststart', str(temporary_video)]
    try:
        font = ImageFont.truetype('arial.ttf', max(16, round(vw / 64)))
    except OSError:
        font = ImageFont.load_default()
    processes = []
    completed = False
    rows = []
    previous = None
    missing = 0
    frame_bytes = size[0] * size[1]
    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=CREATE_NO_WINDOW)
        processes.append(proc)
        if make_video:
            video_proc = subprocess.Popen(video_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
            processes.append(video_proc)
            encoder = subprocess.Popen(encode_command, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
            processes.append(encoder)
        while not cancel.is_set():
            data = read_frame(proc.stdout, frame_bytes)
            if len(data) != frame_bytes:
                break
            if make_video:
                video_data = read_frame(video_proc.stdout, vw * vh * 3)
                if len(video_data) != vw * vh * 3: raise RuntimeError('無法讀取對應的追蹤影片畫面')
            index = len(rows) * step
            frame = np.frombuffer(data, dtype=np.uint8).reshape(size[1], size[0])
            result = detect(frame, background, threshold, min_area, max_area, previous, region_mask)
            row = [index, round(index / fps, 6), '', '', '', '', '', 'missing']
            if result:
                sx, sy, area = result
                xx = x0 + sx * rw / size[0]
                yy = y0 + sy * rh / size[1]
                row = [index, round(index / fps, 6), round(xx, 2), round(yy, 2),
                       round((xx - x0) / rw, 5), round((yy - y0) / rh, 5),
                       'top' if yy < split else 'bottom', 'detected']
                previous = (sx, sy)
                missing = 0
            else:
                missing += 1
                if missing >= 5:
                    previous = None
            rows.append(row)
            if make_video: encoder.stdin.write(annotated_frame(video_data, video_size, (width, height), roi, split, row, font, polygon))
            if len(rows) % 30 == 0:
                report(f'追蹤中：{min(index / fps, duration):.1f} / {duration:.1f} 秒；已偵測 {sum(r[7] == "detected" for r in rows)} / {len(rows)}', frame.copy(), result)
            if max_frames and len(rows) >= max_frames:
                break
        if cancel.is_set():
            raise InterruptedError()
        if max_frames:
            proc.terminate()
            if make_video: video_proc.terminate()
        proc.stdout.close()
        error = proc.stderr.read().decode('utf-8', errors='replace')
        proc.wait()
        video_error = encode_error = ''
        if make_video:
            video_proc.stdout.close(); encoder.stdin.close()
            video_error = video_proc.stderr.read().decode('utf-8', errors='replace')
            encode_error = encoder.stderr.read().decode('utf-8', errors='replace')
            video_proc.wait(); encoder.wait()
        if not max_frames and (proc.returncode or (make_video and video_proc.returncode)):
            raise RuntimeError(f'影片解碼失敗：{error} {video_error}')
        if make_video and encoder.returncode:
            raise RuntimeError(f'追蹤影片輸出失敗：{encode_error}')
        completed = True
    finally:
        if not completed:
            for child in processes:
                if child.poll() is None:
                    child.kill()
            for child in processes:
                child.wait()
            for child in processes:
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
    if not rows:
        raise ValueError('影片沒有可分析的畫面')
    from fish_visuals import create_images
    report('正在產生熱區圖和軌跡圖')
    heat = output.with_name(output.stem + '_heatmap.png')
    trail = output.with_name(output.stem + '_trajectory.png')
    temp_heat = temporary_video.parent / 'heat.png'
    temp_trail = temporary_video.parent / 'trail.png'
    create_images(path, roi, split, polygon, rows, temp_heat, temp_trail)
    if cancel.is_set(): raise InterruptedError()
    # Write after completion, so cancellation cannot masquerade as a complete analysis.
    with output.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['frame', 'time_s', 'x_px', 'y_px', 'x_relative', 'y_relative', 'zone', 'status'])
        writer.writerows(rows)
    summary = output.with_name(output.stem + '_summary.csv')
    top = bottom = distance = 0.0
    transitions = 0
    for a, b in zip(rows, rows[1:]):
        if a[7] != 'detected' or b[7] != 'detected':
            continue
        dt = b[1] - a[1]
        if a[6] == 'top': top += dt
        else: bottom += dt
        distance += math.hypot(b[2] - a[2], b[3] - a[3])
        transitions += a[6] != b[6]
    detected = sum(r[7] == 'detected' for r in rows)
    fields = [('video', str(path)), ('video_fps', fps), ('sampling_every_n_frames', step),
              ('roi_x_px', x0), ('roi_y_px', y0), ('roi_width_px', rw), ('roi_height_px', rh),
              ('divider_y_px', split), ('threshold', threshold), ('min_area_scaled_px', min_area),
              ('polygon_xy', json.dumps(polygon)),
              ('max_area_scaled_px', max_area), ('analysis_width_px', size[0]), ('analysis_height_px', size[1]),
              ('samples', len(rows)), ('detected_samples', detected), ('missing_samples', len(rows)-detected),
              ('tracking_video_generated', int(make_video)),
              ('detected_fraction', detected / len(rows)), ('top_observed_s', top), ('bottom_observed_s', bottom),
              ('distance_observed_px', distance), ('observed_zone_transitions', transitions)]
    with summary.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f); writer.writerow(['metric', 'value']); writer.writerows(fields)
    tracked_video = output.with_name(output.stem + '_tracked.mp4')
    if make_video: temporary_video.replace(tracked_video)
    else: tracked_video = None
    temp_heat.replace(heat); temp_trail.replace(trail)
    return output, summary, tracked_video, detected, len(rows)


class App:
    def __init__(self, root):
        self.root = root
        root.title('魚隻位置追蹤與上下層分析')
        self.path = None; self.info = None; self.roi = None; self.split = None; self.polygon = None; self.corner = None
        self.image = None; self.tkimage = None; self.start = None; self.mode = 'roi'
        self.messages = queue.Queue(); self.cancel = threading.Event(); self.running = False
        bar = ttk.Frame(root, padding=8); bar.pack(fill='x')
        self.open_btn = ttk.Button(bar, text='1. 選擇影片', command=self.open_video); self.open_btn.pack(side='left', padx=3)
        self.roi_btn = ttk.Button(bar, text='2. 重選範圍', command=self.select_roi); self.roi_btn.pack(side='left', padx=3)
        self.div_btn = ttk.Button(bar, text='3. 設定分界線', command=self.select_split); self.div_btn.pack(side='left', padx=3)
        self.run_btn = ttk.Button(bar, text='4. 開始分析並儲存', command=self.start_tracking); self.run_btn.pack(side='left', padx=3)
        self.cancel_btn = ttk.Button(bar, text='取消分析', command=self.cancel.set, state='disabled'); self.cancel_btn.pack(side='left', padx=3)
        self.review_btn = ttk.Button(bar, text='手動修正結果', command=self.review); self.review_btn.pack(side='left', padx=3)
        self.language = tk.StringVar(value='中文')
        selector = ttk.Combobox(bar, textvariable=self.language, values=('中文','English'), state='readonly', width=8)
        selector.pack(side='left', padx=4)
        selector.bind('<<ComboboxSelected>>', self.change_language)
        options = ttk.Frame(root, padding=(8, 0)); options.pack(fill='x')
        self.step = tk.StringVar(value='5'); self.threshold = tk.StringVar(value='15')
        self.minarea = tk.StringVar(value='50'); self.maxarea = tk.StringVar(value='5000')
        self.option_labels = []
        for label, var, width in [('每幾影格取樣', self.step, 5), ('偵測閾值', self.threshold, 5),
                                  ('最小面積', self.minarea, 6), ('最大面積', self.maxarea, 6)]:
            widget = ttk.Label(options, text=label); widget.pack(side='left', padx=(8,2)); self.option_labels.append(widget)
            ttk.Entry(options, textvariable=var, width=width).pack(side='left')
        self.make_video = tk.BooleanVar(value=True)
        self.video_check = ttk.Checkbutton(options, text='輸出追蹤影片（取消可加快）', variable=self.make_video)
        self.video_check.pack(side='left', padx=8)
        self.canvas = tk.Canvas(root, width=960, height=540, bg='#222222', cursor='crosshair')
        self.canvas.pack(padx=8, pady=8)
        self.canvas.bind('<ButtonPress-1>', self.down); self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.up)
        self.status = tk.StringVar(value='請選擇影片，然後在畫面上拖曳框選水槽內部。')
        ttk.Label(root, textvariable=self.status, padding=8, wraplength=950).pack(fill='x')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.poll)

    def open_video(self):
        path = filedialog.askopenfilename(title='選擇影片', filetypes=[('影片', '*.avi *.mp4 *.mov *.mkv *.m4v'), ('所有檔案', '*.*')])
        if not path: return
        try:
            info = metadata(path)
            factor = min(960/info[0], 540/info[1], 1)
            dw, dh = max(1, round(info[0]*factor)), max(1, round(info[1]*factor))
            image = grab_image(path, 0, dw, dh)
            self.path, self.info, self.image = path, info, image
            self.dw, self.dh = dw, dh
            self.roi = None; self.split = None; self.polygon = None; self.mode = 'roi'
            self.draw(); self.status.set('在畫面上拖曳框選水槽可活動範圍；之後可點選分界線。')
        except Exception as exc: messagebox.showerror('無法讀取影片', str(exc))

    def draw(self):
        if self.image is None: return
        self.canvas.delete('all'); self.tkimage = ImageTk.PhotoImage(self.image)
        self.canvas.create_image(0, 0, anchor='nw', image=self.tkimage)
        if self.roi:
            x, y, w, h = self.roi; sx = self.dw/self.info[0]; sy = self.dh/self.info[1]
            points = self.polygon or [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]
            coords = [(px*sx,py*sy) for px,py in points]
            self.canvas.create_line(*(v for p in coords+[coords[0]] for v in p),fill='lime',width=2)
            for px,py in coords: self.canvas.create_oval(px-6,py-6,px+6,py+6,fill='lime')
            if self.split is not None:
                self.canvas.create_line(x*sx,self.split*sy,(x+w)*sx,self.split*sy,fill='yellow',width=2)
    def select_roi(self):
        if self.image: self.mode='roi'; self.status.set('拖曳框選水槽可活動的範圍。')
    def select_split(self):
        if self.roi: self.mode='split'; self.status.set('在綠色方框內點一下，設定上下層黃色分界線。')
    def down(self, event):
        if self.running or self.image is None: return
        if self.polygon:
            sx=self.dw/self.info[0]; sy=self.dh/self.info[1]
            for i,(x,y) in enumerate(self.polygon):
                if math.hypot(event.x-x*sx,event.y-y*sy)<14:
                    self.corner=i; return
        if self.mode == 'split' and self.roi:
            x,y,w,h=self.roi; yy=round(event.y*self.info[1]/self.dh)
            if y < yy < y+h:
                self.split=yy; self.draw(); self.status.set('分界線已設定，可開始分析或重新調整。')
            return
        self.start=(min(max(event.x,0),self.dw), min(max(event.y,0),self.dh))
    def drag(self, event):
        if self.corner is not None:
            px=min(max(round(event.x*self.info[0]/self.dw),0),self.info[0]-1)
            py=min(max(round(event.y*self.info[1]/self.dh),0),self.info[1]-1)
            candidate=list(self.polygon); candidate[self.corner]=(px,py)
            if valid_polygon(candidate):
                self.polygon=candidate
                xs=[p[0] for p in candidate]; ys=[p[1] for p in candidate]
                self.roi=(min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys))
                self.split=min(max(self.split,min(ys)+1),max(ys)-1)
                self.draw()
            return
        if self.start and self.mode == 'roi':
            self.draw(); self.canvas.create_rectangle(*self.start, min(max(event.x,0),self.dw), min(max(event.y,0),self.dh), outline='lime', width=2)
    def up(self, event):
        if self.corner is not None:
            self.corner=None; self.status.set('可拖曳綠色角點調整範圍；點擊可調整黃色分界線。'); return
        if not self.start or self.mode != 'roi': return
        ax,ay=self.start; bx=min(max(event.x,0),self.dw); by=min(max(event.y,0),self.dh); self.start=None
        left,right=sorted((round(ax*self.info[0]/self.dw),round(bx*self.info[0]/self.dw)))
        top,bottom=sorted((round(ay*self.info[1]/self.dh),round(by*self.info[1]/self.dh)))
        if right-left < 10 or bottom-top < 10: return
        self.roi=(left,top,right-left,bottom-top); self.split=(top+bottom)//2; self.mode='split'
        self.polygon=[(left,top),(right,top),(right,bottom),(left,bottom)]
        self.draw(); self.status.set('拖曳四個綠色角點貼合水槽；點一下可調整黃色上下層分界線。')
    def start_tracking(self):
        if not self.path or not self.roi: messagebox.showwarning('尚未選擇範圍', '請先選擇影片並框選水槽。'); return
        try:
            step,threshold,mina,maxa = map(int,(self.step.get(),self.threshold.get(),self.minarea.get(),self.maxarea.get()))
            if step < 1 or not 1 <= threshold <= 255 or mina < 1 or maxa < mina: raise ValueError()
        except ValueError: messagebox.showerror('設定錯誤', '取樣間隔與面積必須為正整數，閾值須介於 1–255，最大面積須大於等於最小面積。'); return
        output=filedialog.asksaveasfilename(title='儲存追蹤結果',defaultextension='.csv',initialfile=Path(self.path).stem+'_tracking.csv',filetypes=[('CSV','*.csv')])
        if not output: return
        if not self.make_video.get() and Path(output).with_name(Path(output).stem + '_tracked.mp4').exists():
            messagebox.showwarning('請更換檔名', '同名追蹤影片已存在。請使用新的檔名，避免誤以為舊影片是本次結果。'); return
        related = [Path(output).with_name(Path(output).stem + suffix)
                   for suffix in ('_summary.csv', '_tracked.mp4', '_heatmap.png', '_trajectory.png')]
        existing = [p.name for p in related if p.exists()]
        if existing and not messagebox.askyesno('檔案已存在', '以下檔案已存在，是否覆寫？\n' + '\n'.join(existing)):
            return
        self.running=True; self.cancel.clear()
        for b in (self.open_btn,self.roi_btn,self.div_btn,self.run_btn,self.review_btn): b.config(state='disabled')
        self.cancel_btn.config(state='normal')
        args=(self.path,self.roi,self.split,step,threshold,mina,maxa,output)
        def worker():
            try: self.messages.put(('done',track(*args, lambda *v:self.messages.put(('progress',v)), self.cancel, polygon=list(self.polygon), make_video=video_enabled)))
            except InterruptedError: self.messages.put(('cancelled',None))
            except Exception as exc: self.messages.put(('error',str(exc)))
        video_enabled=self.make_video.get()
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind, value=self.messages.get_nowait()
                if kind == 'progress':
                    self.status.set(value[0])
                    if len(value)>1:
                        frame, result=value[1:]; img=Image.fromarray(frame).convert('RGB'); img.thumbnail((self.dw,self.dh),RESAMPLE)
                        # Separate analysis preview; retain original image for ROI editing.
                        self.preview=ImageTk.PhotoImage(img); self.canvas.delete('all'); self.canvas.create_image(0,0,anchor='nw',image=self.preview)
                        if result:
                            sx,sy,_=result; px=sx*img.width/frame.shape[1]; py=sy*img.height/frame.shape[0]
                            self.canvas.create_oval(px-5,py-5,px+5,py+5,outline='red',width=2)
                else:
                    self.running=False
                    for b in (self.open_btn,self.roi_btn,self.div_btn,self.run_btn,self.review_btn): b.config(state='normal')
                    self.cancel_btn.config(state='disabled'); self.draw()
                    if kind=='done':
                        out,summary,video,detected,total=value; self.status.set(f'完成：偵測 {detected}/{total} 個取樣畫面。')
                        video_text = str(video) if video else '未輸出（快速模式）'
                        messagebox.showinfo('分析完成',f'追蹤檔：{out}\n摘要檔：{summary}\n追蹤影片：{video_text}\n熱區圖及軌跡圖已存於相同資料夾。\n偵測率：{detected}/{total} ({detected/total:.1%})\n請檢查追蹤結果，確認未誤判。')
                    elif kind=='error': self.status.set('分析失敗'); messagebox.showerror('分析失敗',value)
                    else: self.status.set('已取消，未輸出結果。')
        except queue.Empty: pass
        self.root.after(100,self.poll)
    def close(self):
        if self.running:
            self.cancel.set(); self.root.withdraw()
            def wait_close():
                if self.running: self.root.after(100, wait_close)
                else: self.root.destroy()
            wait_close()
        else: self.root.destroy()

    def review(self):
        from fish_review import Review
        Review(self.root, english=self.language.get() == 'English')

    def change_language(self, event=None):
        english = self.language.get() == 'English'
        self.root.title('Fish tracking and tank analysis' if english else '魚隻位置追蹤與上下層分析')
        labels = (('1. Open video','2. Select region','3. Set divider','4. Analyze and save','Cancel','Manual correction') if english else
                  ('1. 選擇影片','2. 重選範圍','3. 設定分界線','4. 開始分析並儲存','取消分析','手動修正結果'))
        for widget, label in zip((self.open_btn,self.roi_btn,self.div_btn,self.run_btn,self.cancel_btn,self.review_btn),labels): widget.config(text=label)
        options = ('Sample every N frames','Threshold','Minimum area','Maximum area') if english else ('每幾影格取樣','偵測閾值','最小面積','最大面積')
        for widget,label in zip(self.option_labels,options): widget.config(text=label)
        self.video_check.config(text='Export video (uncheck for speed)' if english else '輸出追蹤影片（取消可加快）')


def main():
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        root=tk.Tk(); root.withdraw(); messagebox.showerror('缺少 FFmpeg','找不到 ffmpeg 或 ffprobe。請安裝 FFmpeg 並加入 PATH。'); return
    root=tk.Tk(); App(root); root.mainloop()

if __name__ == '__main__': main()

