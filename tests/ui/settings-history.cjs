const {JSDOM}=require('jsdom');const dom=new JSDOM('<div id="root"></div>',{url:'https://example.test'});Object.assign(global,{window:dom.window,document:dom.window.document,localStorage:dom.window.localStorage,HTMLElement:dom.window.HTMLElement,IS_REACT_ACT_ENVIRONMENT:true});
global.requestAnimationFrame=()=>0;global.cancelAnimationFrame=()=>{};global.getComputedStyle=window.getComputedStyle.bind(window);global.MutationObserver=window.MutationObserver;
global.Event=window.Event;global.CustomEvent=window.CustomEvent;
window.matchMedia=()=>({matches:false,addEventListener:()=>{},removeEventListener:()=>{}});
const React=require('react'),{act}=React,{createRoot}=require('react-dom/client'),assert=require('node:assert/strict'),{Settings}=require(process.env.SETTINGS_BUNDLE);
(async()=>{
const me={id:'test',username:'alice',role:'user',profile:'sandbox',totp:true};
const response=data=>({ok:true,status:200,json:async()=>data});
let resolvePermissions,first=true;
global.fetch=async path=>{if(path==='/api/me/permissions'&&first){first=false;return new Promise(r=>resolvePermissions=r)}return response(path==='/api/me/permissions'?{'feature:own_subscriptions':true}:path==='/api/me/providers'?{providers:[],oauth:[],current:{provider:'',model:''},assigned:null}:{});};
localStorage.setItem('shroom-settings-section:alice:sandbox','model');
let root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(Settings,{me,onClose:()=>{}})));
assert.equal(document.querySelector('.settings-main h1').textContent,'Вхід і безпека');
await act(async()=>resolvePermissions(response({'feature:own_subscriptions':true})));
assert.equal(document.querySelector('.settings-main h1').textContent,'Модель і підписки');await act(async()=>root.unmount());
root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(Settings,{me:{...me,username:'bob'},onClose:()=>{}})));assert.equal(document.querySelector('.settings-main h1').textContent,'Вхід і безпека');await act(async()=>root.unmount());
global.fetch=async()=>response({});root=createRoot(document.getElementById('root'));await act(async()=>root.render(React.createElement(Settings,{me,onClose:()=>{}})));assert.equal(document.querySelector('.settings-main h1').textContent,'Вхід і безпека');await act(async()=>root.unmount());console.log('PASS: delayed permission restore, account isolation, unavailable section fallback');
})().catch(e=>{console.error(e);process.exitCode=1});
