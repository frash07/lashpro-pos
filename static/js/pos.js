(()=>{
  const prices=JSON.parse(document.getElementById("prices").textContent);
  const format=n=>"KSh "+new Intl.NumberFormat("en-KE",{minimumFractionDigits:2,maximumFractionDigits:2}).format(Number(n)||0);
  const field=(row,name)=>row.querySelector('[name$="-'+name+'"]');
  const activeRows=selector=>[...document.querySelectorAll(selector)].filter(row=>{const deleted=row.querySelector('input[name$="-DELETE"]');return !deleted||!deleted.checked;});
  const rows=()=>activeRows("#items [data-item-row]");
  const payments=()=>activeRows("#payments [data-payment-row]");
  let orderTotal=0;
  let paymentListExpanded=false;
  let noticeTimer=null;
  function showNotice(message){const notice=document.getElementById("pos-notice");notice.textContent=message;notice.hidden=false;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>notice.hidden=true,5200);}
  const register=document.getElementById("register-panel"),backdrop=document.getElementById("register-backdrop"),registerToggle=document.getElementById("register-toggle");
  function setRegisterOpen(open){register.classList.toggle("is-open",open);backdrop.hidden=!open;registerToggle.setAttribute("aria-expanded",String(open));document.body.classList.toggle("register-open",open);}
  registerToggle.addEventListener("click",()=>setRegisterOpen(!register.classList.contains("is-open")));
  document.getElementById("register-close").addEventListener("click",()=>setRegisterOpen(false));
  backdrop.addEventListener("click",()=>setRegisterOpen(false));
  document.addEventListener("keydown",event=>{if(event.key==="Escape")setRegisterOpen(false);});
  document.getElementById("apply-promo").addEventListener("click",()=>showNotice("Promo and student codes are not connected yet. No discount was applied."));

  function cardFor(kind,id){return [...document.querySelectorAll("[data-catalog-card]")].find(card=>card.dataset.itemKind===kind&&card.dataset.itemId===String(id));}
  function remainingBalance(exceptRow=null){
    let cash=0,mpesa=0;
    payments().filter(row=>row!==exceptRow).forEach(row=>{
      const amount=Number(field(row,"amount").value)||0;
      if(field(row,"method").value==="CASH")cash+=amount;
      else if(field(row,"method").value==="MPESA")mpesa+=amount;
    });
    const afterMpesa=Math.max(0,orderTotal-Math.min(mpesa,orderTotal));
    return Math.max(0,afterMpesa-Math.min(cash,afterMpesa));
  }
  function update(){
    let total=0,count=0,cash=0,mpesa=0,discountTotal=0;
    rows().forEach(row=>{
      const product=field(row,"product"),service=field(row,"service");
      const productId=product.value,serviceId=service.value,kind=productId?"product":serviceId?"service":"";
      const id=productId||serviceId,selected=!!id,tech=field(row,"technician");
      const techField=row.querySelector("[data-technician-field]");
      if(techField){techField.hidden=!serviceId;tech.required=!!serviceId;if(!serviceId)tech.value="";}
      const hasErrors=row.dataset.hasErrors==="true";
      row.classList.toggle("is-empty",!selected&&!hasErrors);
      if(!selected)return;
      const card=cardFor(kind,id);
      const select=productId?product:service;
      const name=card?.dataset.itemName||select.options[select.selectedIndex]?.text.split(" — KSh ")[0]||"Catalog item";
      const meta=card?.dataset.itemMeta||(kind==="service"?"Lash service":"Retail product");
      const price=Number(prices[kind==="product"?"products":"services"][id])||0;
      const qtyField=field(row,"quantity"),quantity=Math.max(1,Number(qtyField.value)||1),discountField=field(row,"discount");
      const discount=discountField?Number(discountField.value)||0:0,lineTotal=Math.max(0,price*quantity-discount);
      discountTotal+=discount;
      const lineThumb=row.querySelector("[data-line-thumb]"),catalogImage=card?.querySelector("[data-catalog-image]");
      if(lineThumb&&catalogImage)lineThumb.src=catalogImage.src;
      row.querySelector("[data-line-name]").textContent=name;
      row.querySelector("[data-line-meta]").textContent=meta;
      row.querySelector("[data-line-quantity]").textContent="× "+quantity;
      row.querySelector("[data-line-total]").textContent=format(lineTotal);
      total+=lineTotal;count+=quantity;
    });

    payments().forEach(row=>{
      const method=field(row,"method"),amount=Number(field(row,"amount").value)||0,reference=row.querySelector("[data-reference-field]");
      const value=method.value;
      row.classList.toggle("is-empty",!value&&amount===0&&!(field(row,"reference").value||""));
      if(reference)reference.hidden=value!=="MPESA";
      if(value==="CASH")cash+=amount;else if(value==="MPESA")mpesa+=amount;
    });
    orderTotal=total;
    const mpesaApplied=Math.min(mpesa,total),afterMpesa=Math.max(0,total-mpesaApplied);
    const cashApplied=Math.min(cash,afterMpesa),change=Math.max(0,cash-cashApplied);
    const balance=Math.max(0,afterMpesa-cashApplied);
    const vat=total*16/116;
    document.getElementById("subtotal").textContent=format(total-vat);
    document.getElementById("discount-total").textContent="− "+format(discountTotal);
    document.getElementById("vat").textContent=format(vat);
    document.getElementById("total").textContent=format(total);
    document.getElementById("submit-total").textContent=format(total);
    document.getElementById("cash-received").textContent=format(cash);
    document.getElementById("cash-change").textContent=format(change);
    document.getElementById("mpesa-pending").textContent=format(mpesa);
    document.getElementById("balance-due").textContent=format(balance);
    document.getElementById("cart-empty").hidden=count>0;document.querySelector(".register-panel").classList.toggle("has-items",count>0);
    const hasPayments=payments().some(row=>field(row,"method").value||field(row,"amount").value||field(row,"reference").value);
    document.getElementById("payments").hidden=!paymentListExpanded&&!hasPayments;
    document.getElementById("register-count").textContent=String(count);document.getElementById("register-mobile-total").textContent=format(total);
  }

  function addRow(containerId,templateId,prefix){
    const totalForms=document.getElementById("id_"+prefix+"-TOTAL_FORMS"),index=Number(totalForms.value);
    const host=document.getElementById(containerId),template=document.getElementById(templateId);
    host.insertAdjacentHTML("beforeend",template.innerHTML.replaceAll("__prefix__",index));
    totalForms.value=index+1;
    return host.lastElementChild;
  }
  function addPayment(method){
    const row=addRow("payments","payment-template","payments");
    field(row,"method").value=method;
    field(row,"method").dispatchEvent(new Event("change",{bubbles:true}));
    const due=remainingBalance(row);field(row,"amount").value=due>0?due.toFixed(2):"";
    update();
    if(method==="MPESA")field(row,"reference").focus();
  }

  document.querySelectorAll("[data-catalog-card]").forEach(card=>card.addEventListener("click",()=>{
    const kind=card.dataset.itemKind,id=card.dataset.itemId;
    const existing=rows().find(row=>field(row,kind).value===id);
    if(existing){const qty=field(existing,"quantity");qty.value=(Number(qty.value)||1)+1;qty.dispatchEvent(new Event("input",{bubbles:true}));return;}
    let row=rows().find(item=>!field(item,"product").value&&!field(item,"service").value);
    if(!row)row=addRow("items","item-template","items");
    field(row,kind).value=id;
    const other=field(row,kind==="product"?"service":"product");other.value="";
    if(kind==="service"&&document.getElementById("default-technician").value)field(row,"technician").value=document.getElementById("default-technician").value;
    field(row,kind).dispatchEvent(new Event("change",{bubbles:true}));
  }));

  document.getElementById("default-technician").addEventListener("change",event=>{
    rows().forEach(row=>{if(field(row,"service").value)field(row,"technician").value=event.target.value;});
  });
  document.getElementById("checkout").addEventListener("input",update);
  document.getElementById("checkout").addEventListener("change",event=>{
    const row=event.target.closest("[data-item-row]");
    if(row&&event.target.name.endsWith("-product")&&event.target.value){field(row,"service").value="";field(row,"technician").value="";}
    if(row&&event.target.name.endsWith("-service")&&event.target.value){field(row,"product").value="";if(!field(row,"technician").value)field(row,"technician").value=document.getElementById("default-technician").value;}
    update();
  });
  document.querySelectorAll("[data-add-payment]").forEach(button=>button.addEventListener("click",()=>{
    paymentListExpanded=true;
    document.querySelectorAll("[data-add-payment]").forEach(option=>option.setAttribute("aria-pressed",String(option===button)));
    document.getElementById("split-payment").setAttribute("aria-pressed","false");
    document.getElementById("mpesa-phone-field").hidden=button.dataset.addPayment!=="MPESA";
    addPayment(button.dataset.addPayment);
  }));
  document.getElementById("split-payment").addEventListener("click",()=>{
    paymentListExpanded=true;
    document.querySelectorAll("[data-add-payment]").forEach(option=>option.setAttribute("aria-pressed","false"));
    document.getElementById("split-payment").setAttribute("aria-pressed","true");
    document.getElementById("mpesa-phone-field").hidden=true;
    document.getElementById("payments").hidden=false;
    document.querySelector("#payments select[name$='-method']")?.focus();
  });
  document.getElementById("fill-balance").addEventListener("click",()=>{
    let target=payments().slice().reverse().find(row=>field(row,"method").value==="CASH")||payments().slice().reverse().find(row=>field(row,"method").value==="MPESA");
    if(!target)target=payments().find(row=>!field(row,"method").value);
    if(!target){if(!document.querySelector(".cash-option").disabled){target=addRow("payments","payment-template","payments");field(target,"method").value="CASH";}else{showNotice("Open a cash session before entering cash. Add a manual M-Pesa reference instead.");return;}}
    if(!field(target,"method").value)field(target,"method").value=document.querySelector(".cash-option").disabled?"MPESA":"CASH";
    const due=remainingBalance(target);field(target,"amount").value=due.toFixed(2);update();
    if(field(target,"method").value==="MPESA"&&!field(target,"reference").value)field(target,"reference").focus();
  });
  document.getElementById("checkout").addEventListener("click",event=>{
    const step=event.target.closest("[data-qty-step]");
    if(step){const row=step.closest("[data-item-row]"),qty=field(row,"quantity");qty.value=Math.max(1,(Number(qty.value)||1)+Number(step.dataset.qtyStep));qty.dispatchEvent(new Event("input",{bubbles:true}));return;}
    const remove=event.target.closest("[data-remove]");
    if(remove){const row=remove.closest("[data-item-row],[data-payment-row]"),deleted=row.querySelector('input[name$="-DELETE"]');if(deleted){deleted.checked=true;row.hidden=true;}update();}
  });
  document.getElementById("clear-items").addEventListener("click",()=>{
    const hasItems=rows().some(row=>field(row,"product").value||field(row,"service").value);
    const hasPayments=payments().some(row=>field(row,"method").value||field(row,"amount").value||field(row,"reference").value);
    if(!hasItems&&!hasPayments)return;
    if(!window.confirm("Clear this order and its payment entries?"))return;
    document.querySelectorAll("#items [data-item-row]").forEach(row=>{field(row,"product").value="";field(row,"service").value="";field(row,"technician").value="";field(row,"quantity").value="1";const discount=field(row,"discount"),reason=field(row,"discount_reason"),deleted=row.querySelector('input[name$="-DELETE"]');if(discount)discount.value="0.00";if(reason)reason.value="";if(deleted)deleted.checked=false;row.dataset.hasErrors="false";row.hidden=false;});
    document.querySelectorAll("#payments [data-payment-row]").forEach(row=>{field(row,"method").value="";field(row,"amount").value="";field(row,"reference").value="";const deleted=row.querySelector('input[name$="-DELETE"]');if(deleted)deleted.checked=false;row.hidden=false;});
    document.getElementById("promo-code").value="";
    update();
  });
  let activeCategory="all";
  const search=document.getElementById("catalog-search");
  function filterCatalog(){
    const query=search.value.trim().toLocaleLowerCase();
    document.querySelectorAll("[data-catalog-card]").forEach(card=>{
      card.hidden=(activeCategory!=="all"&&card.dataset.category!==activeCategory)||!card.textContent.toLocaleLowerCase().includes(query);
    });
    const trainingEmpty=document.getElementById("training-empty");trainingEmpty.hidden=activeCategory!=="training"||!!query;
  }
  search.addEventListener("input",filterCatalog);
  search.addEventListener("keydown",event=>{
    if(event.key!=="Enter")return;
    const query=search.value.trim().toLocaleLowerCase();
    const exactSku=[...document.querySelectorAll("[data-item-sku]")].filter(card=>card.dataset.itemSku.toLocaleLowerCase()===query);
    if(exactSku.length===1&&!exactSku[0].disabled){event.preventDefault();exactSku[0].click();search.value="";filterCatalog();}
  });
  document.querySelectorAll(".catalog-filter").forEach(button=>button.addEventListener("click",()=>{
    activeCategory=button.dataset.category;
    document.querySelectorAll(".catalog-filter").forEach(tab=>{const selected=tab===button;tab.classList.toggle("is-active",selected);tab.setAttribute("aria-pressed",String(selected));});
    filterCatalog();
  }));
  document.querySelectorAll("[data-payment-row]").forEach(row=>{const method=field(row,"method");method.addEventListener("change",update);});
  document.getElementById("checkout").addEventListener("submit",()=>{
    const button=document.querySelector(".checkout-submit");button.disabled=true;button.textContent="Completing sale…";
  });
  const clock=document.getElementById("clock");
  if(clock){const tick=()=>clock.textContent=new Intl.DateTimeFormat("en-KE",{hour:"numeric",minute:"2-digit"}).format(new Date());tick();setInterval(tick,30000);}
  const online=document.getElementById("network-status");
  function networkState(){online.textContent=navigator.onLine?"Online":"Offline";online.parentElement.classList.toggle("is-offline",!navigator.onLine);}
  window.addEventListener("online",networkState);window.addEventListener("offline",networkState);networkState();
  let installPrompt=null;
  const installButton=document.getElementById("install-app");
  window.addEventListener("beforeinstallprompt",event=>{event.preventDefault();installPrompt=event;installButton.hidden=false;});
  installButton.addEventListener("click",async()=>{if(!installPrompt)return;installPrompt.prompt();await installPrompt.userChoice;installPrompt=null;installButton.hidden=true;});
  filterCatalog();
  update();
})();
