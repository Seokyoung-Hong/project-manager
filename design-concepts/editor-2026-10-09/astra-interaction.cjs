const {chromium}=require('C:/Users/tjrdu/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright');
const fs=require('fs'),path=require('path');
(async()=>{const browser=await chromium.launch();const result=[];
 for(const mode of ['a','b']){
 const page=await browser.newPage({viewport:{width:390,height:844},colorScheme:'light'});await page.goto(`http://127.0.0.1:8879/design-concepts/editor-2026-10-09/astra-${mode}.html`);await page.waitForFunction(()=>window.demoReady);
 const ed=page.locator('[data-field="progress"] .ProseMirror');
 for(const [text,node] of [['# ','heading'],['- ','bulletList'],['[ ] ','taskList'],['``` ','codeBlock']]){await ed.click();await page.keyboard.press('Control+a');await page.keyboard.press('Backspace');await page.keyboard.type(text);const actual=await page.evaluate(()=>window.demoEditors.get('progress').getJSON().content[0].type);if(actual!==node)throw Error(text+': '+actual)}
 await ed.click();await page.keyboard.press('Control+a');await page.keyboard.press('Backspace');await page.keyboard.press('ArrowDown');
 await page.evaluate(()=>window.demoEditors.get('progress').commands.setContent('<p></p>'));
 await ed.evaluate(el=>{const d=new DataTransfer();d.setData('text/plain','https://example.com/guide');el.dispatchEvent(new ClipboardEvent('paste',{clipboardData:d,bubbles:true,cancelable:true}))});
 if(!(await ed.innerHTML()).includes('href="https://example.com/guide"'))throw Error('URL 붙여넣기 실패');
 const desc=page.locator('[data-field="description"] .ProseMirror');await desc.click();await page.keyboard.press('Control+Home');await page.keyboard.down('Shift');for(let i=0;i<5;i++)await page.keyboard.press('ArrowRight');await page.keyboard.up('Shift');await page.locator('.bubble').waitFor({state:'visible'});await page.locator('.bubble [data-command=italic]').click();
 if(!(await desc.innerHTML()).includes('<em>'))throw Error('말풍선 기울임 실패');
 const field=mode==='a'?'summary':'description';await page.locator(`[data-field="${field}"] [data-open-tools]`).click();await page.locator('.bubble').waitFor({state:'visible'});await page.keyboard.press('Tab');await page.keyboard.press('Enter');
 await page.locator(`[data-field="${field}"] [data-open-tools]`).click();await page.screenshot({path:path.join(__dirname,`shots/astra-${mode}-390-bubble.png`)});await page.keyboard.press('Escape');
 await desc.click();await desc.dispatchEvent('compositionstart');await page.keyboard.insertText('조합확인');await page.locator('#task h3').click();const deferred=await page.locator('[data-field="description"] .state').innerText();if(deferred==='이 화면에 반영됨')throw Error('조합 중 반영됨');await desc.dispatchEvent('compositionend');await desc.click();await page.locator('#task h3').click();
 result.push({시안:mode,마크다운입력규칙:true,URL붙여넣기:true,선택말풍선:true,말풍선키보드:true,합성IME조합중반영보류:true,실제OS한글IME:'자동화로 확인 불가'});await page.close();}
 fs.writeFileSync(path.join(__dirname,'astra-interaction-results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();})().catch(e=>{console.error(e);process.exit(1)});
