from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

CANVAS_W=1080
CANVAS_H=1920
HEADER_H=504
DIVIDER_Y=503
VIDEO_Y=504
VIDEO_H=1416
BG_TOP=(28,30,32)
BG_BOTTOM=(14,15,16)
ORANGE=(242,112,45)
WHITE=(245,245,244)
DIVIDER=(205,205,202)
BRAND=(155,157,160)
# Anchored to this file, not the working directory, so the layout renders
# identically however the worker is started.
LOGO_PATH=Path(__file__).resolve().parent/'assets'/'kn-watermark.png'
BRAND_TEXT='KNOWLEDGE NUGGETS'
BRAND_FONT='/usr/share/fonts/truetype/noto/NotoSansDisplay-Light.ttf'
QUESTION_FONT='/usr/share/fonts/truetype/noto/NotoSansDisplay-ExtraCondensedBlack.ttf'
CAPTION_FONT='/usr/share/fonts/truetype/noto/NotoSansDisplay-Black.ttf'
CAPTION_FONT_NAME='Noto Sans Display Black'

# YouTube paints its own furniture over a Short. These bounds come from a phone
# capture, converted into canvas coordinates. Nothing the layout owns may sit
# inside them and still expect to be seen.
UI_TOP_H=154
UI_BOTTOM_Y=1800

# The header carries the core question and nothing else. Its gaps are measured
# from the bottom of YouTube's icon row rather than the frame edge, so the
# visible space above and below the text reads as equal on a real phone.
QUESTION_LINE1_Y=225
QUESTION_LINE_STEP=87
QUESTION_LINE2_Y=QUESTION_LINE1_Y+QUESTION_LINE_STEP
QUESTION_SIZE=86
QUESTION_MAX_W=880

# The mark sits low and centred, clear of the channel row at UI_BOTTOM_Y. It is
# kept small on purpose: the source asset is only 48x49px, so every extra pixel
# of height is visible enlargement.
FOOTER_FADE_TOP=1400
LOGO_H=76
LOGO_Y=1580
BRAND_Y=1676
BRAND_SIZE=21
BRAND_TRACKING=5.5

# Captions never cross this margin. They wrap instead of leaving the frame.
CAPTION_MARGIN=96
CAPTION_SIZE=66
CAPTION_LINE_STEP=84
CAPTION_CENTRE_Y=round(HEADER_H+0.58*(LOGO_Y-HEADER_H))
CAPTION_MAX_W=CANVAS_W-2*CAPTION_MARGIN
CAPTION_WORD_SPACE=1.0

def _tracked_text(draw, xy, text, font, fill, tracking):
    widths=[draw.textlength(ch,font=font) for ch in text]
    total=sum(widths)+tracking*(len(text)-1)
    x,y=xy
    for ch,cw in zip(text,widths):
        draw.text((x,y),ch,font=font,fill=fill)
        x += cw+tracking
    return total

def build_header(question_lines, out_path):
    """Build the full-frame brand overlay: header, clear middle, footer mark.

    One RGBA image carries both fixed elements, so the renderer composites the
    layout in a single overlay pass and the footage stays visible between them.
    """
    if not isinstance(question_lines,(list,tuple)) or len(question_lines)!=2:
        raise ValueError('Layout lock requires exactly two core-question lines.')
    q1,q2=[str(x).strip().upper() for x in question_lines]
    if not q1 or not q2:
        raise ValueError('Core-question lines cannot be empty.')

    im=Image.new('RGBA',(CANVAS_W,CANVAS_H),(0,0,0,0))

    header=Image.new('RGBA',(CANVAS_W,HEADER_H))
    px=header.load()
    for y in range(HEADER_H):
        t=y/max(1,HEADER_H-1)
        rgb=tuple(round(BG_TOP[i]*(1-t)+BG_BOTTOM[i]*t) for i in range(3))
        for x in range(CANVAS_W):
            px[x,y]=rgb+(255,)
    draw=ImageDraw.Draw(header)
    qfont=ImageFont.truetype(QUESTION_FONT,QUESTION_SIZE)
    for text,y,fill in ((q1,QUESTION_LINE1_Y,WHITE),(q2,QUESTION_LINE2_Y,ORANGE)):
        box=draw.textbbox((0,0),text,font=qfont)
        width=box[2]-box[0]
        if width>QUESTION_MAX_W:
            raise ValueError(f'Core-question line too wide for locked layout ({width}px > {QUESTION_MAX_W}px): {text}')
        draw.text(((CANVAS_W-width)/2,y),text,font=qfont,fill=fill)
    draw.rectangle((0,DIVIDER_Y,CANVAS_W-1,DIVIDER_Y),fill=DIVIDER)
    im.paste(header,(0,0))

    # A soft scrim rather than a solid bar: the mark stays legible over bright
    # footage without costing any picture area.
    scrim=Image.new('RGBA',(CANVAS_W,CANVAS_H),(0,0,0,0))
    sd=ImageDraw.Draw(scrim)
    for y in range(FOOTER_FADE_TOP,CANVAS_H):
        t=(y-FOOTER_FADE_TOP)/max(1,CANVAS_H-FOOTER_FADE_TOP-1)
        sd.line([(0,y),(CANVAS_W,y)],fill=(10,11,12,round(248*(t**1.15))))
    im.alpha_composite(scrim)

    logo=Image.open(LOGO_PATH).convert('RGBA')
    lw=round(logo.width*(LOGO_H/logo.height))
    logo=logo.resize((lw,LOGO_H),Image.Resampling.LANCZOS)
    im.paste(logo,((CANVAS_W-lw)//2,LOGO_Y),logo)

    mark=ImageDraw.Draw(im)
    brand_font=ImageFont.truetype(BRAND_FONT,BRAND_SIZE)
    widths=[mark.textlength(ch,font=brand_font) for ch in BRAND_TEXT]
    tw=sum(widths)+BRAND_TRACKING*(len(BRAND_TEXT)-1)
    _tracked_text(mark,((CANVAS_W-tw)/2,BRAND_Y),BRAND_TEXT,brand_font,BRAND,BRAND_TRACKING)

    Path(out_path).parent.mkdir(parents=True,exist_ok=True)
    im.save(out_path)
    return str(out_path)

def caption_ass_fontsize():
    """The ASS Fontsize that renders as large as CAPTION_SIZE does in Pillow.

    Pillow sizes a font by its em square; libass sizes it by ascent plus
    descent. Passing the same number to both makes libass draw the text about
    28% too small, which leaves the word positions correct but the gaps between
    them far too wide. Deriving the value keeps the two in step if the font or
    the size ever changes.
    """
    ascent,descent=ImageFont.truetype(CAPTION_FONT,CAPTION_SIZE).getmetrics()
    return ascent+descent


def caption_layout(words):
    """Place caption words inside the margin, wrapping and centring each line.

    Returns (word, centre_x, centre_y) per word so the renderer can position and
    animate each one independently, and no line can ever leave the frame.
    """
    font=ImageFont.truetype(CAPTION_FONT,CAPTION_SIZE)
    probe=ImageDraw.Draw(Image.new('RGB',(1,1)))
    # A natural word space. The 6px caption outline already adds visual
    # separation, so anything wider reads as words drifting apart.
    gap=probe.textlength(' ',font=font)*CAPTION_WORD_SPACE
    widths=[probe.textlength(word,font=font) for word in words]

    lines=[]
    current=[]
    current_w=0.0
    for word,width in zip(words,widths):
        extra=width if not current else gap+width
        if current and current_w+extra > CAPTION_MAX_W:
            lines.append((current,current_w))
            current,current_w=[(word,width)],width
        else:
            current.append((word,width))
            current_w+=extra
    if current:
        lines.append((current,current_w))

    placed=[]
    y=CAPTION_CENTRE_Y-(len(lines)-1)*CAPTION_LINE_STEP/2
    for line,total in lines:
        x=(CANVAS_W-total)/2
        for word,width in line:
            placed.append((word,round(x+width/2),round(y)))
            x+=width+gap
        y+=CAPTION_LINE_STEP
    return placed
