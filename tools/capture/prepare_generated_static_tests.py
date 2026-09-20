from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT=Path("captures/generated/test-media")
OUT.mkdir(parents=True,exist_ok=True)

def make(size, lines, stem):
    w,h=size
    im=Image.new("RGB",size,"#07111f")
    d=ImageDraw.Draw(im)
    for x in range(0,w,80): d.rectangle((x,0,x+39,h),fill="#142b46")
    for y in range(0,h,60): d.line((0,y,w,y),fill="#ef3054",width=5)
    d.rectangle((35,25,w-35,h-25),outline="#ffffff",width=8)
    font=ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf",max(54,h//7))
    spacing=12
    boxes=[d.textbbox((0,0),line,font=font,stroke_width=2) for line in lines]
    heights=[b[3]-b[1] for b in boxes]; total=sum(heights)+spacing*(len(lines)-1)
    y=(h-total)//2
    for line,b,lh in zip(lines,boxes,heights):
        lw=b[2]-b[0]; d.text(((w-lw)//2,y),line,font=font,fill="white",stroke_width=5,stroke_fill="#000000"); y+=lh+spacing
    im.save(OUT/(stem+".png"))
    im.save(OUT/(stem+".jpg"),format="JPEG",quality=92,subsampling=2,optimize=False,progressive=False)

make((1920,462),("THERMALRIGHT","9.16 TEST","GENERATED FRAME"),"generated_9_16")
make((1280,480),("THERMALRIGHT","6 INCH TEST","GENERATED FRAME"),"generated_6")
