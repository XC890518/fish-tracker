import csv
import json
import math
import subprocess
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk
import fish_tracker as ft

HEADERS = ['frame','time_s','x_px','y_px','x_relative','y_relative','zone','status','correction']


def load_data(path):
    path=Path(path)
    summary=path.with_name(path.stem+'_summary.csv')
    with summary.open(encoding='utf-8-sig',newline='') as f:
        settings={row['metric']:row['value'] for row in csv.DictReader(f)}
    with path.open(encoding='utf-8-sig',newline='') as f:
        records=list(csv.DictReader(f))
    if not records: raise ValueError('CSV 沒有資料')
    source=Path(settings['video'])
    if not source.is_absolute(): source=path.parent/source
    if not source.exists(): raise ValueError('找不到原影片：'+str(source))
    roi=tuple(int(settings[k]) for k in ('roi_x_px','roi_y_px','roi_width_px','roi_height_px'))
    x,y,w,h=roi
    polygon=json.loads(settings.get('polygon_xy','null')) or [(x,y),(x+w,y),(x+w,y+h),(x,y+h)]
    return records, settings, source, roi, polygon


def numeric_row(r):
    return [int(r['frame']),float(r['time_s']),float(r['x_px']) if r['x_px'] else '',
            float(r['y_px']) if r['y_px'] else '',r['x_relative'],r['y_relative'],r['zone'],r['status']]


def save_corrected(output, records, settings, source, roi, polygon, report):
    output=Path(output); summary=output.with_name(output.stem+'_summary.csv'); video=output.with_name(output.stem+'_tracked.mp4')
    if source.resolve() in [output.resolve(),summary.resolve(),video.resolve()]: raise ValueError('輸出名稱不可與原影片相同')
    width,height,fps,duration=ft.metadata(source); step=int(settings['sampling_every_n_frames']); split=float(settings['divider_y_px'])
    rows=[numeric_row(r) for r in records]
    if any(row[0] != i*step for i,row in enumerate(rows)): raise ValueError('CSV 影格順序或取樣間隔與摘要不符')
    scale=min(1,1280/width); vw=max(2,round(width*scale/2)*2); vh=max(2,round(height*scale/2)*2)
    filt=f'select=not(mod(n\\,{step})),scale={vw}:{vh}'
    decode=['ffmpeg','-v','error','-i',str(source),'-vf',filt,'-vsync','0','-f','rawvideo','-pix_fmt','rgb24','-']
    try: font=ImageFont.truetype('arial.ttf',max(16,round(vw/64)))
    except OSError: font=ImageFont.load_default()
    with tempfile.TemporaryDirectory(prefix='fish_review_',dir=output.parent) as tmp:
        tmp=Path(tmp); temp_video=tmp/'video.mp4'
        encode=['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{vw}x{vh}','-r',str(fps/step),'-i','-','-an','-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',str(temp_video)]
        dec=enc=None
        try:
            dec=subprocess.Popen(decode,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=ft.CREATE_NO_WINDOW)
            enc=subprocess.Popen(encode,stdin=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=ft.CREATE_NO_WINDOW)
            for i,row in enumerate(rows):
                data=ft.read_frame(dec.stdout,vw*vh*3)
                if len(data)!=vw*vh*3: raise ValueError('原影片影格數少於追蹤資料')
                enc.stdin.write(ft.annotated_frame(data,(vw,vh),(width,height),roi,split,row,font,polygon))
                if i%30==0: report(f'重新產生影片 {i+1}/{len(rows)}')
            # Stop decoder after the last requested frame; some analyses are partial.
            dec.terminate(); dec.stdout.close(); dec.wait(); enc.stdin.close()
            err=enc.stderr.read().decode('utf-8',errors='replace'); enc.wait()
            if enc.returncode: raise RuntimeError('影片編碼失敗：'+err)
        finally:
            for proc in (dec,enc):
                if proc and proc.poll() is None: proc.kill(); proc.wait()
                if proc:
                    for stream in (proc.stdin,proc.stdout,proc.stderr):
                        if stream and not stream.closed: stream.close()
        with (tmp/'data.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=HEADERS,extrasaction='ignore'); writer.writeheader()
            for record in records: writer.writerow(record)
        top=bottom=distance=0.; transitions=0
        for a,b in zip(rows,rows[1:]):
            if a[7]!='detected' or b[7]!='detected': continue
            dt=b[1]-a[1]
            if a[6]=='top': top+=dt
            else: bottom+=dt
            distance+=math.hypot(b[2]-a[2],b[3]-a[3]); transitions+=a[6]!=b[6]
        detected=sum(r[7]=='detected' for r in rows)
        settings.update(video=str(source.resolve()), samples=len(rows),detected_samples=detected,
            tracking_video_generated=1,
            missing_samples=len(rows)-detected,detected_fraction=detected/len(rows),
            top_observed_s=top,bottom_observed_s=bottom,distance_observed_px=distance,
            observed_zone_transitions=transitions,manual_corrections=sum(r.get('correction')=='manual' for r in records))
        with (tmp/'summary.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f); writer.writerow(['metric','value']); writer.writerows(settings.items())
        from fish_visuals import create_images
        report('正在產生熱區圖和軌跡圖')
        create_images(source,roi,split,polygon,rows,tmp/'heat.png',tmp/'trail.png')
        heat=output.with_name(output.stem+'_heatmap.png'); trail=output.with_name(output.stem+'_trajectory.png')
        (tmp/'data.csv').replace(output); (tmp/'summary.csv').replace(summary); temp_video.replace(video)
        (tmp/'heat.png').replace(heat); (tmp/'trail.png').replace(trail)
    return output,summary,video,heat,trail


class Review:
    def __init__(self,parent,english=False):
        path=filedialog.askopenfilename(parent=parent,title='選擇追蹤位置 CSV',filetypes=[('CSV','*.csv')])
        if not path:return
        try:
            self.records,self.settings,self.source,self.roi,self.polygon=load_data(path)
            self.width,self.height,self.fps,_=ft.metadata(self.source)
        except Exception as e: messagebox.showerror('無法開啟',str(e),parent=parent); return
        self.path=Path(path); self.i=0; self.changed=False; self.busy=False
        self.window=tk.Toplevel(parent); self.window.title('手動修正魚隻位置')
        bar=ttk.Frame(self.window,padding=5); bar.pack(fill='x')
        ttk.Button(bar,text='上一筆',command=lambda:self.move(-1)).pack(side='left')
        ttk.Button(bar,text='下一筆',command=lambda:self.move(1)).pack(side='left')
        self.jump=tk.StringVar(value='0'); ttk.Label(bar,text='時間（秒）').pack(side='left',padx=5)
        ttk.Entry(bar,textvariable=self.jump,width=9).pack(side='left')
        ttk.Button(bar,text='跳至時間',command=self.goto).pack(side='left')
        ttk.Button(bar,text='標記未偵測',command=self.missing).pack(side='left',padx=5)
        ttk.Button(bar,text='另存修正結果',command=self.save).pack(side='left')
        self.label=tk.StringVar(); ttk.Label(self.window,textvariable=self.label).pack()
        factor=min(960/self.width,540/self.height,1); self.dw=round(self.width*factor); self.dh=round(self.height*factor)
        self.canvas=tk.Canvas(self.window,width=self.dw,height=self.dh,bg='black'); self.canvas.pack()
        self.canvas.bind('<Button-1>',self.click)
        self.window.bind('<Left>',lambda e:self.move(-1)); self.window.bind('<Right>',lambda e:self.move(1))
        self.window.protocol('WM_DELETE_WINDOW',self.close)
        if english:
            self.window.title('Manual position correction')
            translations={'上一筆':'Previous','下一筆':'Next','時間（秒）':'Time (seconds)', '跳至時間':'Go to time','標記未偵測':'Mark missing','另存修正結果':'Save corrected results'}
            for widget in bar.winfo_children():
                try:
                    current=widget.cget('text')
                    if current in translations: widget.config(text=translations[current])
                except tk.TclError: pass
        self.draw()
    def draw(self):
        r=self.records[self.i]
        try:
            # Select by decoded frame number, not an approximate timestamp seek.
            frame_no=int(r['frame'])
            raw=ft.run_command(['ffmpeg','-v','error','-i',str(self.source),'-vf',
                f'select=eq(n\\,{frame_no}),scale={self.dw}:{self.dh}', '-vsync','0',
                '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
            if len(raw)!=self.dw*self.dh*3: raise ValueError('找不到對應的原始影格')
            image=Image.frombytes('RGB',(self.dw,self.dh),raw)
        except Exception as e: messagebox.showerror('讀取畫面失敗',str(e),parent=self.window); return
        self.photo=ImageTk.PhotoImage(image); self.canvas.delete('all'); self.canvas.create_image(0,0,image=self.photo,anchor='nw')
        sx=self.dw/self.width; sy=self.dh/self.height
        pts=[(x*sx,y*sy) for x,y in self.polygon]; self.canvas.create_line(*(v for p in pts+[pts[0]] for v in p),fill='lime',width=2)
        x,y,w,h=self.roi; split=float(self.settings['divider_y_px']); self.canvas.create_line(x*sx,split*sy,(x+w)*sx,split*sy,fill='yellow',width=2)
        if r['status']=='detected' and r['x_px'] and r['y_px']:
            px=float(r['x_px'])*sx; py=float(r['y_px'])*sy
            self.canvas.create_oval(px-7,py-7,px+7,py+7,outline='red',width=3)
        self.label.set(f"{self.i+1}/{len(self.records)} | {float(r['time_s']):.2f} 秒 | {r['status']} | {r.get('correction','auto') or 'auto'}：點擊魚的位置修正；左右方向鍵切換")
    def move(self,n):
        if self.busy:return
        self.i=max(0,min(len(self.records)-1,self.i+n)); self.draw()
    def goto(self):
        try: t=float(self.jump.get()); self.i=min(range(len(self.records)),key=lambda i:abs(float(self.records[i]['time_s'])-t)); self.draw()
        except ValueError: messagebox.showerror('時間錯誤','請輸入秒數',parent=self.window)
    def click(self,event):
        if self.busy:return
        px=event.x*self.width/self.dw; py=event.y*self.height/self.dh
        mask=Image.new('1',(self.dw,self.dh)); ImageDraw.Draw(mask).polygon([(x*self.dw/self.width,y*self.dh/self.height) for x,y in self.polygon],fill=1)
        if not (0<=event.x<self.dw and 0<=event.y<self.dh and mask.getpixel((event.x,event.y))):
            messagebox.showwarning('範圍外','請在綠色範圍內選取魚的位置。',parent=self.window); return
        x,y,w,h=self.roi; r=self.records[self.i]
        r.update(x_px=f'{px:.2f}',y_px=f'{py:.2f}',x_relative=f'{(px-x)/w:.5f}',y_relative=f'{(py-y)/h:.5f}',zone='top' if py<float(self.settings['divider_y_px']) else 'bottom',status='detected',correction='manual')
        self.changed=True; self.draw()
    def missing(self):
        if self.busy:return
        r=self.records[self.i]; r.update(x_px='',y_px='',x_relative='',y_relative='',zone='',status='missing',correction='manual'); self.changed=True; self.draw()
    def save(self):
        if self.busy:return
        output=filedialog.asksaveasfilename(parent=self.window,title='另存修正後 CSV',defaultextension='.csv',initialfile=self.path.stem+'_corrected.csv',filetypes=[('CSV','*.csv')])
        if not output:return
        paths=[Path(output)] + [Path(output).with_name(Path(output).stem+suffix)
               for suffix in ('_summary.csv','_tracked.mp4','_heatmap.png','_trajectory.png')]
        if any(p.exists() for p in paths) and not messagebox.askyesno('覆寫檔案','一個或多個輸出檔已存在，確定覆寫？',parent=self.window): return
        self.busy=True; self.label.set('準備輸出，請稍候…')
        def work():
            try:
                result=save_corrected(output,self.records,self.settings.copy(),self.source,self.roi,self.polygon,lambda text:self.window.after(0,self.label.set,text))
                self.window.after(0,lambda:self.finished(result,None))
            except Exception as e:
                msg=str(e); self.window.after(0,lambda:self.finished(None,msg))
        threading.Thread(target=work,daemon=True).start()
    def finished(self,result,error):
        self.busy=False
        if error: messagebox.showerror('輸出失敗',error,parent=self.window)
        else:
            self.changed=False; messagebox.showinfo('輸出完成','\n'.join(map(str,result)),parent=self.window)
        self.draw()
    def close(self):
        if self.busy: messagebox.showwarning('輸出中','請等輸出完成。',parent=self.window); return
        if self.changed and not messagebox.askyesno('尚未儲存','修正尚未儲存，確定關閉？',parent=self.window):return
        self.window.destroy()
