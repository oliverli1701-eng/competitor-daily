"""轻量中文日报 PDF：正文与网站共用已核验事实，嵌入字体便于离线阅读。"""
from pathlib import Path
from html import escape
import os

from .presentation import build_cards, SECTIONS, short_date
from .core import DATE_FIELDS, parse_at
from .branding import institution_name, normalize_profile


def write_pdf(report, target):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
    from .render import event_markdown
    profile = normalize_profile(report.get('branding'))

    font=Path(os.environ.get('REPORT_PDF_FONT',str(Path(__file__).resolve().parent.parent/'assets/ReportSans.ttc')))
    if not font.is_file():raise ValueError('PDF 中文字体缺失，请配置 REPORT_PDF_FONT')
    if 'ReportSans' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('ReportSans',str(font)))
    style=ParagraphStyle('body',fontName='ReportSans',fontSize=9.2,leading=15,textColor=colors.HexColor('#28303b'),wordWrap='CJK',spaceAfter=5)
    title=ParagraphStyle('title',parent=style,fontSize=23,leading=32,spaceAfter=10)
    heading=ParagraphStyle('heading',parent=style,fontSize=14,leading=22,spaceBefore=14,spaceAfter=7,keepWithNext=True,textColor=colors.HexColor(profile['accent_color'] or '#163d54'))
    summary_heading=ParagraphStyle('summary-heading',parent=heading,fontSize=11,leading=17,spaceBefore=9,spaceAfter=4)
    summary_line=ParagraphStyle('summary-line',parent=style,fontSize=9,leading=13,spaceAfter=2)
    sub=ParagraphStyle('sub',parent=style,fontSize=10.5,leading=17,spaceBefore=9,keepWithNext=True)
    small=ParagraphStyle('small',parent=style,fontSize=8,leading=12,textColor=colors.HexColor('#647180'))
    cards=build_cards(report);year=int(report['date'][:4]);story=[]
    def p(text,kind=style):return Paragraph(escape(str(text)),kind)
    institution = institution_name(profile)
    story += [p(profile['report_title'],title),p('  /  '.join(filter(None, [report['date'], institution])),sub),p('信息截至 '+report['as_of'][:16].replace('T',' ')+'（北京时间） · '+str(len(cards))+' 项赛事',small),Spacer(1,12)]
    if report.get('demo'):
        story += [p('演示日报 · 非实时赛事资讯',sub),p('用于预览版式与功能。导入自己的学院清单后，使用自己的 API 或 Agent 检索能力生成日报。',small),Spacer(1,8)]
    for key,label in SECTIONS:
        selected=[c for c in cards if key in c['sections']]
        story.append(p(label+' · '+str(len(selected))+' 项',summary_heading))
        if not selected:story.append(p('本期无新增条目。',small))
        for card in selected:
            node=card['next'];date=short_date(node[2],year)+' '+node[1] if node else ''
            story.append(p(card['name']+('  /  '+date if date else ''),summary_line))
    story.append(p('参赛信息与官方来源',heading))
    for card in cards:
        for index,event in enumerate(card['events']):
            block=[]
            if index==0:block.append(p(card['name']+'  ·  '+' / '.join(card['levels']),heading))
            if len(card['events'])>1:block.append(p(event['view_track'] or event.get('edition',''),sub))
            display=dict(event)
            for field in DATE_FIELDS:
                if event.get(field) and 'T' in event[field]:
                    display[field]=parse_at(event[field]).strftime('%Y-%m-%d %H:%M')+'（北京时间）'
            for line in event_markdown(display):
                if line.startswith('- [报名 / 提交入口]('):
                    url=event.get('entry_url','');block.append(Paragraph('<link href="'+escape(url,quote=True)+'" color="#1a6585">报名 / 提交入口</link>',style))
                else:block.append(p(line.removeprefix('- ')))
            for node in event.get('milestones',[]):
                if node.get('date'):block.append(p('赛程：'+node['name']+' · '+short_date(node['date'],year)))
            for rule in event.get('track_requirements',[]):
                facts=[{'online':'线上','offline':'线下','hybrid':'线上 + 线下'}.get(rule.get('mode'),''),rule.get('mode_details',''),*rule.get('eligibility',[]),*rule.get('deliverables',[])]
                text='；'.join(str(x) for x in facts if x)
                if text:block.append(p(rule.get('name','分赛题')+'：'+text))
            for source in event.get('sources',[]):
                url=source.get('url','')
                if url.startswith(('https://','http://')):
                    block.append(Paragraph('<link href="'+escape(url,quote=True)+'" color="#1a6585">来源：'+escape(source.get('title') or '官方通知')+'</link>',small))
            # Keep short event details with their sources; long tracks can still split naturally.
            story.append(KeepTogether(block));story.append(Spacer(1,7))
    # A final spacer alone can overflow an otherwise full frame and create a blank page.
    if story and isinstance(story[-1],Spacer):story.pop()
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    temp=target.with_suffix('.pdf.tmp')
    def footer(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#d8dfe4'));canvas.line(40,37,A4[0]-40,37)
        canvas.setFont('ReportSans',8);canvas.setFillColor(colors.HexColor('#647180'))
        footer_text = report['date']+'  ·  '+(profile['footer_text'] or profile['brand_name'])
        if report.get('demo'):
            footer_text += '  ·  演示数据'
        if profile['website_url']:
            footer_text += '  ·  '+profile['website_url']
        # Long user-owned names/URLs must stay clear of the page number.
        while pdfmetrics.stringWidth(footer_text, 'ReportSans', 8) > A4[0] - 110:
            footer_text = footer_text[:-2] + '…'
        canvas.drawString(40,23,footer_text)
        canvas.drawRightString(A4[0]-40,23,str(doc.page))
    try:
        SimpleDocTemplate(str(temp),pagesize=A4,rightMargin=40,leftMargin=40,topMargin=40,bottomMargin=49,title=profile['report_title']+' · '+report['date'],author=profile['brand_name']).build(story,onFirstPage=footer,onLaterPages=footer)
        temp.replace(target)
    finally:temp.unlink(missing_ok=True)
    return target
