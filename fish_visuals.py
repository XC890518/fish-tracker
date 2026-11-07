from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter
from PIL import Image, ImageDraw, ImageFont
import fish_tracker as ft


def create_images(source, roi, split, polygon, rows, heat_path, trail_path):
    width,height,_,_=ft.metadata(source)
    scale=min(1,1280/width)
    w=max(2,round(width*scale)); h=max(2,round(height*scale))
    background=ft.grab_image(source,0,w,h).convert('RGB')
    sx=w/width; sy=h/height
    x,y,rw,rh=roi
    polygon=polygon or [(x,y),(x+rw,y),(x+rw,y+rh),(x,y+rh)]
    points=[(round(px*sx),round(py*sy)) for px,py in polygon]
    mask=Image.new('L',(w,h),0); ImageDraw.Draw(mask).polygon(points,fill=255)
    density=np.zeros((h,w),dtype=np.float32)
    coords=[]
    for row in rows:
        if row[7]=='detected' and row[2]!='' and row[3]!='':
            px=min(w-1,max(0,round(float(row[2])*sx))); py=min(h-1,max(0,round(float(row[3])*sy)))
            density[py,px]+=1; coords.append((px,py))
        else: coords.append(None)
    density=gaussian_filter(density,sigma=max(4,round(w/100)))
    density*=np.asarray(mask,dtype=np.float32)/255
    maximum=float(density.max())
    if maximum:
        v=density/maximum
        # Blue -> cyan -> yellow -> red, with transparency at low density.
        red=np.clip(4*v-1.5,0,1); green=np.clip(1.5-np.abs(4*v-2),0,1); blue=np.clip(1.5-4*v,0,1)
        rgb=np.stack((red,green,blue),axis=2)*255
        base=np.asarray(background,dtype=np.float32)
        alpha=(np.clip(v*3,0,0.72))[:,:,None]
        heat=Image.fromarray(np.uint8(base*(1-alpha)+rgb*alpha))
    else: heat=background.copy()
    trail=background.copy(); td=ImageDraw.Draw(trail)
    for a,b in zip(coords,coords[1:]):
        if a is not None and b is not None: td.line((a,b),fill='#ff3344',width=2)
    for point in coords:
        if point is not None: td.ellipse((point[0]-1,point[1]-1,point[0]+1,point[1]+1),fill='#ff3344')
    try: font=ImageFont.truetype('arial.ttf',max(15,w//80))
    except OSError: font=ImageFont.load_default()
    for image,title in [(heat,'HEATMAP | blue: low   red: high'),(trail,'TRAJECTORY | gaps: missing samples')]:
        draw=ImageDraw.Draw(image); draw.line(points+[points[0]],fill='#00ff00',width=2)
        draw.line((round(x*sx),round(split*sy),round((x+rw)*sx),round(split*sy)),fill='#ffff00',width=2)
        box=draw.textbbox((0,0),title,font=font); draw.rectangle((4,4,box[2]+16,box[3]+16),fill='black'); draw.text((10,7),title,font=font,fill='white')
    heat.save(heat_path); trail.save(trail_path)
