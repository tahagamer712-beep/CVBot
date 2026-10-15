"""Minimal dependency-free DOCX writer for CVs (replaces python-docx; lxml won't build on Termux).
Produces valid WordprocessingML with full RTL support. Word/LibreOffice open it natively."""
import os
import zipfile
from xml.sax.saxutils import escape

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
RELS = 'http://schemas.openxmlformats.org/package/2006/relationships'
CORE = 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties'
DC = 'http://purl.org/dc/elements/1.1/'
DCTERMS = 'http://purl.org/dc/terms/'
APP = 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'

CONTENT_TYPES = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="{CT}">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''

RELS_ROOT = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{RELS}">
<Relationship Id="rId1" Type="{RELS}/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="{RELS}/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="{RELS}/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''

DOC_RELS = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{RELS}">
</Relationships>'''

CORE_XML = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="{CORE}" xmlns:dc="{DC}" xmlns:dcterms="{DCTERMS}">
<dc:title>CV</dc:title><dc:creator>CV Bot</dc:creator>
</cp:coreProperties>'''

APP_XML = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="{APP}">
<Application>CV Bot</Application>
</Properties>'''


class DocxBuilder:
    def __init__(self, lang='ar'):
        self.lang = lang
        self.rtl = lang == 'ar'
        self.paras = []

    def para(self, text, size=11, bold=False, align=None, color=None,
             space_after=4, shade=None, border_bottom=None):
        """align: left/right/center. color: 'RRGGBB'. shade: 'RRGGBB' fill."""
        if align is None:
            align = 'right' if self.rtl else 'left'
        self.paras.append({
            'text': str(text or ''), 'size': size, 'bold': bold,
            'align': align, 'color': color, 'space_after': space_after,
            'shade': shade, 'border_bottom': border_bottom,
            'rtl': self.rtl,
        })

    def _para_xml(self, p):
        t = escape(p['text'])
        # runs: split long text into single run (Word handles bidi)
        rpr = [f'<w:rFonts w:ascii="Amiri" w:hAnsi="Amiri" w:cs="Amiri"/>',
               f'<w:sz w:val="{int(p["size"] * 2)}"/><w:szCs w:val="{int(p["size"] * 2)}"/>']
        if p['bold']:
            rpr.append('<w:b/><w:bCs/>')
        if p['color']:
            rpr.append(f'<w:color w:val="{p["color"]}"/>')
        if p['rtl']:
            rpr.append('<w:rtl/>')
        ppr = [f'<w:jc w:val="{p["align"]}"/>' ,
               f'<w:spacing w:after="{int(p["space_after"] * 20)}"/>']
        if p['rtl']:
            ppr.append('<w:bidi/>')
        if p['shade']:
            ppr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{p["shade"]}"/>')
        if p['border_bottom']:
            c, sz = p['border_bottom']
            ppr.append(f'<w:pBdr><w:bottom w:val="single" w:sz="{sz}" '
                       f'w:space="1" w:color="{c}"/></w:pBdr>')
        return (
            '<w:p><w:pPr>' + ''.join(ppr) + '</w:pPr>'
            f'<w:r><w:rPr>{"".join(rpr)}</w:rPr><w:t xml:space="preserve">{t}</w:t></w:r></w:p>'
        )

    def save(self, path):
        body = ''.join(self._para_xml(p) for p in self.paras)
        sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="1021" w:right="1021" w:bottom="1021" '
                'w:left="1021" w:header="708" w:footer="708"/></w:sectPr>')
        doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               f'<w:document xmlns:w="{W}"><w:body>{body}{sect}</w:body></w:document>')
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr('[Content_Types].xml', CONTENT_TYPES)
            z.writestr('_rels/.rels', RELS_ROOT)
            z.writestr('word/_rels/document.xml.rels', DOC_RELS)
            z.writestr('word/document.xml', doc)
            z.writestr('docProps/core.xml', CORE_XML)
            z.writestr('docProps/app.xml', APP_XML)
        return path
