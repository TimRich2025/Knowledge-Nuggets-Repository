from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

CANVAS_W=1080
CANVAS_H=1920
HEADER_H=429
DIVIDER_Y=428
VIDEO_Y=429
VIDEO_H=1491
BG_TOP=(28,30,32)
BG_BOTTOM=(14,15,16)
ORANGE=(242,112,45)
WHITE=(245,245,244)
DIVIDER=(205,205,202)
BRAND=(155,157,160)
LOGO_PATH=Path('assets/kn-watermark.png')
BRAND_TEXT='KNOWLEDGE NUGGETS'
BRAND_FONT='/usr/share/fonts/truetype/noto/NotoSansDisplay-Light.ttf'
QUESTION_FONT='/usr/share/fonts/truetype/noto/NotoSansDisplay-ExtraCondensedBlack.ttf'

# Immutable coordinates scaled from the approved Knowledge Nuggets master layout.
LOGO_H=56
LOGO_Y=39
BRAND_Y=111
BRAND_SIZE=19
BRAND_TRACKING=6
ORANGE_LINE_Y=180
ORANGE_LINE_W=130
ORANGE_LINE_H=2
QUESTION_LINE1_Y=222
QUESTION_LINE2_Y=300
QUESTION_SIZE=82
QUESTION_MAX_W=880

def _tracked_text(draw, xy, text, font, fill, tracking):
    widths=[draw.textlength(ch,font=font) for ch in text]
    total=sum(widths)+tracking*(len(text)-1)
    x,y=xy
    for ch,cw in zip(text,widths):
        draw.text((x,y),ch,font=font,fill=fill)
        x += cw+tracking
    return total

def build_header(question_lines, out_path):
    if not isinstance(question_lines,(list,tuple)) or len(question_lines)!=2:
        raise ValueError('Layout lock requires exactly two core-question lines.')
    q1,q2=[str(x).strip().upper() for x in question_lines]
    if not q1 or not q2:
        raise ValueError('Core-question lines cannot be empty.')

    im=Image.new('RGB',(CANVAS_W,HEADER_H))
    px=im.load()
    for y in range(HEADER_H):
        t=y/max(1,HEADER_H-1)
        rgb=tuple(round(BG_TOP[i]*(1-t)+BG_BOTTOM[i]*t) for i in range(3))
        for x in range(CANVAS_W):
            px[x,y]=rgb
    draw=ImageDraw.Draw(im)

    logo=Image.open(LOGO_PATH).convert('RGBA')
    lw=round(logo.width*(LOGO_H/logo.height))
    logo=logo.resize((lw,LOGO_H),Image.Resampling.LANCZOS)
    im.paste(logo,((CANVAS_W-lw)//2,LOGO_Y),logo)

    brand_font=ImageFont.truetype(BRAND_FONT,BRAND_SIZE)
    widths=[draw.textlength(ch,font=brand_font) for ch in BRAND_TEXT]
    tw=sum(widths)+BRAND_TRACKING*(len(BRAND_TEXT)-1)
    _tracked_text(draw,((CANVAS_W-tw)/2,BRAND_Y),BRAND_TEXT,brand_font,BRAND,BRAND_TRACKING)

    x0=(CANVAS_W-ORANGE_LINE_W)//2
    draw.rectangle((x0,ORANGE_LINE_Y,x0+ORANGE_LINE_W-1,ORANGE_LINE_Y+ORANGE_LINE_H-1),fill=ORANGE)

    qfont=ImageFont.truetype(QUESTION_FONT,QUESTION_SIZE)
    for text,y,fill in ((q1,QUESTION_LINE1_Y,WHITE),(q2,QUESTION_LINE2_Y,ORANGE)):
        box=draw.textbbox((0,0),text,font=qfont)
        width=box[2]-box[0]
        if width>QUESTION_MAX_W:
            raise ValueError(f'Core-question line too wide for locked layout ({width}px > {QUESTION_MAX_W}px): {text}')
        draw.text(((CANVAS_W-width)/2,y),text,font=qfont,fill=fill)

    draw.rectangle((0,DIVIDER_Y,CANVAS_W-1,DIVIDER_Y),fill=DIVIDER)
    Path(out_path).parent.mkdir(parents=True,exist_ok=True)
    im.save(out_path)
    return str(out_path)
