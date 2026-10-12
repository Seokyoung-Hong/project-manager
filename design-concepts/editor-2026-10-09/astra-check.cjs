const { chromium } = require('C:/Users/tjrdu/AppData/Local/npm-cache/_npx/e41f203b7505f1fb/node_modules/playwright');
const fs = require('fs');
const path = require('path');
(async()=>{
 const browser = await chromium.launch({headless:true});
 const results=[];fs.mkdirSync(path.join(__dirname,'shots'),{recursive:true});
 for(const mode of ['a','b']) for(const width of [1440,390]){
  const page=await browser.newPage({viewport:{width,height:1000},deviceScaleFactor:1,colorScheme:'light'});const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:8879/design-concepts/editor-2026-10-09/astra-${mode}.html`);
  await page.waitForFunction(()=>window.demoReady===true);await page.evaluate(()=>document.fonts.ready);
  const ed=page.locator('[data-field="description"] .ProseMirror');await ed.click();await page.keyboard.press('Control+End');await page.keyboard.press('Enter');await page.keyboard.insertText('함께 확인할 내용을 추가했습니다.');
  const typed=await ed.innerText();if(!typed.includes('함께 확인할 내용을 추가했습니다.'))throw Error('한글 입력 실패');
  await page.keyboard.press('Control+b');await page.keyboard.insertText(' 중요');await page.keyboard.press('Control+b');
  await page.locator('#task h3').click();
  const md=await page.locator('[data-field="description"] input[type=hidden]').inputValue();if(!md.includes('**중요**')&&!md.includes('** 중요**'))throw Error('굵게 단축키 실패: '+md);
  const mirror=await page.locator('[data-mirror="description"]').innerText();if(!mirror.includes('함께 확인할 내용을 추가했습니다.'))throw Error('읽기 화면 동기화 실패');
  await page.locator('[data-modal="modal-blocked"]').click();await page.locator('#modal-blocked button[type=submit]').click();if(!await page.locator('#modal-blocked .error-message').innerText())throw Error('필수 사유 검증 실패');
  await page.locator('#modal-blocked .ProseMirror').click();await page.keyboard.insertText('검토 자료를 기다리고 있습니다.');await page.locator('#modal-blocked button[type=submit]').click();if(!(await page.locator('#modal-blocked .form-result').innerText()).includes('반영'))throw Error('사유 제출 실패');await page.locator('#modal-blocked .dialog-close').click();
  await ed.click();await page.keyboard.press('Control+Home');await page.keyboard.press('Control+k');await page.locator('#link-dialog input').fill('https://example.com/guide');await page.locator('#link-dialog button[type=button]').click();
  const overflow=await page.evaluate(()=>({doc:document.documentElement.scrollWidth,viewport:innerWidth,editors:window.demoEditors.size}));
  if(overflow.doc>width)throw Error('가로 넘침 '+JSON.stringify(overflow));
  await page.goto(`http://127.0.0.1:8879/design-concepts/editor-2026-10-09/astra-${mode}.html`);await page.waitForFunction(()=>window.demoReady);await page.evaluate(()=>document.fonts.ready);
  await page.screenshot({path:path.join(__dirname,`shots/astra-${mode}-${width}.png`),fullPage:true});
  await page.screenshot({path:path.join(__dirname,`shots/astra-${mode}-${width}-top.png`)});
  results.push({시안:mode,너비:width,편집기:overflow.editors,한글입력:true,굵게단축키:true,읽기동기화:true,필수검증:true,모달제출:true,링크단축키:true,가로넘침:false,오류:errors});await page.close();
 }
 fs.writeFileSync(path.join(__dirname,'astra-check-results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
