<!-- 본문을 고치면 저장소 맨 위에서 privacy.html을 다시 만든다(개발용 markdown 패키지, 런타임 의존성 아님): python -c "import markdown,pathlib;from markdown.extensions.toc import TocExtension,slugify_unicode as s;d=pathlib.Path('core/web/content');h=markdown.markdown(d.joinpath('privacy.md').read_text('utf-8').split('\n',1)[1],extensions=['tables',TocExtension(slugify=s)]);d.joinpath('privacy.html').write_text(h.replace('<table>','<div class=\"table-scroll\"><table>').replace('</table>','</table></div>')+'\n','utf-8',newline='\n')" -->

# 개인정보 처리방침

준비 중입니다.
