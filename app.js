const app = document.querySelector("#app");
const cartDrawer = document.querySelector("[data-cart-drawer]");
const overlay = document.querySelector("[data-overlay]");
const checkoutDialog = document.querySelector("[data-checkout]");
const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const cartKey = "vertice-cart-v1";
let products = [];
let selectedQuantity = 1;
let categoryCarouselTimer = null;
let integrationStatus = { payments: { mode: "demo", configured: false }, whatsapp: { configured: false } };
let checkoutAttemptKey = "";

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function getCart() {
  try {
    const stored = JSON.parse(localStorage.getItem(cartKey) || "[]");
    if (!Array.isArray(stored)) return [];
    return stored.filter((item) =>
      item && typeof item.product_id === "string" &&
      Number.isInteger(item.quantity) && item.quantity > 0
    );
  } catch {
    return [];
  }
}

function saveCart(cart) {
  localStorage.setItem(cartKey, JSON.stringify(cart));
  updateCartCount();
}

function updateCartCount() {
  const count = getCart().reduce((sum, item) => sum + item.quantity, 0);
  document.querySelector("[data-cart-count]").textContent = count > 99 ? "99+" : String(count);
}

function formatPrice(cents) {
  return money.format(cents / 100);
}

async function fetchApi(input, options) {
  try {
    return await fetch(input, options);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error("Não foi possível conectar à loja. Inicie o servidor com `python app.py` e tente novamente.");
    }
    throw error;
  }
}

async function fetchApi(input, options) {
  try {
    return await fetch(input, options);
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error("Não foi possível conectar à loja. Inicie o servidor com `python app.py` e tente novamente.");
    }
    throw error;
  }
}

function productById(id) {
  return products.find((product) => product.id === id);
}

function productPhoto(product, className = "product-photo") {
  if (!product.image_path) {
    return `<span class="product-icon" aria-hidden="true">${escapeHtml(product.icon)}</span>`;
  }
  return `<img class="${className}" src="${escapeHtml(product.image_path)}" alt="${escapeHtml(product.name)}" loading="lazy">`;
}

function stockLabel(stock) {
  if (stock === 0) return { text: "Indisponível", className: "low" };
  if (stock <= 5) return { text: `Últimas ${stock} unidades`, className: "low" };
  return { text: `${stock} em estoque`, className: "" };
}

function productCard(product) {
  const stock = stockLabel(product.stock);
  return `
    <article class="product-card">
      <a href="/produto/${encodeURIComponent(product.id)}" aria-label="Ver ${escapeHtml(product.name)}">
        <div class="product-art visual-${escapeHtml(product.visual)} ${product.image_path ? "product-art-photo" : ""}">
          ${productPhoto(product)}
        </div>
      </a>
      <div class="product-card-content">
        <div class="product-category">${escapeHtml(product.category)}</div>
        <h3 class="product-name"><a href="/produto/${encodeURIComponent(product.id)}">${escapeHtml(product.name)}</a></h3>
        <p class="product-description">${escapeHtml(product.description)}</p>
        <div class="product-card-bottom">
          <div><div class="price">${formatPrice(product.price_cents)}</div><div class="stock-note ${stock.className}">${stock.text}</div></div>
          <button class="card-add" type="button" data-add="${escapeHtml(product.id)}" aria-label="Adicionar ${escapeHtml(product.name)} ao carrinho" ${product.stock === 0 ? "disabled" : ""}>+</button>
        </div>
      </div>
    </article>`;
}

const categoryDefinitions = [
  { name: "Monitores", caption: "Mais detalhe em cada imagem", productId: "monitor-full-hd", icon: "▣" },
  { name: "Teclados", caption: "Digitação no seu ritmo", productId: "teclado-rgb-branco", icon: "⌨" },
  { name: "Periféricos", caption: "Controle e precisão", productId: "mouse-ergonomico", icon: "◉" },
  { name: "Cabos", caption: "Conexões para seu setup", productId: "cabo-hdmi-2m", icon: "⌁" },
  { name: "Escritório", caption: "Conforto para produzir", productId: "cadeira-ergonomica", icon: "◒" },
];

function categoryCard(category) {
  const product = productById(category.productId);
  const count = products.filter((item) => item.category === category.name).length;
  const image = product?.image_path
    ? productPhoto(product, "category-photo")
    : `<span class="category-symbol" aria-hidden="true">${category.icon}</span>`;
  return `
    <button class="category-card" type="button" data-category-filter="${escapeHtml(category.name)}" aria-label="Ver ${count} produtos de ${escapeHtml(category.name)}">
      <span class="category-media">${image}</span>
      <span class="category-copy"><span class="category-name">${escapeHtml(category.name)}</span><span class="category-count">${escapeHtml(category.caption)} · ${count} ${count === 1 ? "produto" : "produtos"}</span></span>
      <span class="category-arrow" aria-hidden="true">↗</span>
    </button>`;
}

function featuredCard(product, eyebrow, headline, copy) {
  return `
    <article class="featured-card">
      <a class="featured-photo" href="/produto/${encodeURIComponent(product.id)}" aria-label="Ver ${escapeHtml(product.name)}">
        ${productPhoto(product, "featured-image")}
      </a>
      <div class="featured-copy">
        <p class="eyebrow">${escapeHtml(eyebrow)}</p>
        <h3>${escapeHtml(headline)}</h3>
        <p>${escapeHtml(copy)}</p>
        <a class="subtle-link" href="/produto/${encodeURIComponent(product.id)}">${escapeHtml(product.name)} <span aria-hidden="true">→</span></a>
      </div>
    </article>`;
}

function startCategoryCarousel() {
  if (categoryCarouselTimer !== null) {
    window.clearInterval(categoryCarouselTimer);
    categoryCarouselTimer = null;
  }
  const track = document.querySelector("[data-category-track]");
  const carousel = track?.parentElement;
  if (!track || !carousel || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const advance = () => {
    const card = track.querySelector(".category-card");
    if (!card) return;
    const atEnd = track.scrollLeft + track.clientWidth >= track.scrollWidth - 8;
    const gap = Number.parseFloat(getComputedStyle(track).columnGap) || 0;
    track.scrollTo({
      left: atEnd ? 0 : track.scrollLeft + card.getBoundingClientRect().width + gap,
      behavior: "smooth",
    });
  };
  const pause = () => {
    if (categoryCarouselTimer !== null) {
      window.clearInterval(categoryCarouselTimer);
      categoryCarouselTimer = null;
    }
  };
  const resume = () => {
    pause();
    categoryCarouselTimer = window.setInterval(advance, 4500);
  };
  carousel.addEventListener("mouseenter", pause);
  carousel.addEventListener("mouseleave", resume);
  carousel.addEventListener("focusin", pause);
  carousel.addEventListener("focusout", resume);
  carousel.addEventListener("touchstart", pause, { passive: true });
  carousel.addEventListener("touchend", resume, { passive: true });
  resume();
}

function renderHome(categoryFilter = null) {
  const heroMonitor = productById("monitor-full-hd");
  const heroKeyboard = productById("teclado-rgb-branco");
  const heroMouse = productById("mouse-ergonomico");
  const spotlightProducts = [
    productById("monitor-full-hd"),
    productById("teclado-rgb-branco"),
    productById("cabo-hdmi-2m"),
  ].filter(Boolean);
  const visibleProducts = categoryFilter
    ? products.filter((product) => product.category === categoryFilter)
    : products;
  app.innerHTML = `
    <div class="page-shell">
      <section class="hero">
        <div class="hero-content">
          <p class="eyebrow">Tecnologia que acompanha você</p>
          <h1>Conecte-se ao que <span>vem pela frente.</span></h1>
          <p class="hero-copy">Cabos, periféricos e equipamentos selecionados para transformar sua rotina de trabalho e lazer.</p>
          <a class="button button-primary hero-link" href="#produtos">Explore os produtos <span aria-hidden="true">→</span></a>
        </div>
        <div class="hero-showcase" aria-label="Destaques do catálogo">
          ${heroMonitor ? `<a class="hero-photo hero-photo-main" href="/produto/${encodeURIComponent(heroMonitor.id)}" aria-label="${escapeHtml(heroMonitor.name)}">${productPhoto(heroMonitor, "hero-image")}</a>` : ""}
          ${heroKeyboard ? `<a class="hero-photo hero-photo-keyboard" href="/produto/${encodeURIComponent(heroKeyboard.id)}" aria-label="${escapeHtml(heroKeyboard.name)}">${productPhoto(heroKeyboard, "hero-image")}</a>` : ""}
          ${heroMouse ? `<a class="hero-photo hero-photo-mouse" href="/produto/${encodeURIComponent(heroMouse.id)}" aria-label="${escapeHtml(heroMouse.name)}">${productPhoto(heroMouse, "hero-image")}</a>` : ""}
          <span class="hero-caption">SELEÇÃO VÉRTICE <span>•</span> TECNOLOGIA PARA O SEU DIA</span>
        </div>
      </section>
      <section class="spotlight-section" aria-labelledby="spotlight-title">
        <div class="section-heading">
          <div><p class="eyebrow">Um setup com a sua cara</p><h2 id="spotlight-title">Escolhas que fazem a diferença</h2></div>
          <a class="subtle-link" href="#produtos">Descobrir catálogo <span aria-hidden="true">→</span></a>
        </div>
        <div class="featured-grid">
          ${spotlightProducts[0] ? featuredCard(spotlightProducts[0], "Imagem imersiva", "Um novo ponto de vista", "Mais espaço para suas ideias, estudos e entretenimento.") : ""}
          ${spotlightProducts[1] ? featuredCard(spotlightProducts[1], "Toque pessoal", "Seu ritmo, suas teclas", "Encontre o teclado que combina com seu jeito de trabalhar.") : ""}
          ${spotlightProducts[2] ? featuredCard(spotlightProducts[2], "Conexão essencial", "Tudo conectado", "Uma conexão de imagem confiável para completar seu espaço.") : ""}
        </div>
      </section>
      <section id="categorias" aria-labelledby="category-title">
        <div class="section-heading">
          <div><p class="eyebrow">Encontre o que procura</p><h2 id="category-title">Explore por categoria</h2></div>
          <div class="carousel-controls">
            <button class="carousel-button" type="button" data-category-scroll="-1" aria-label="Rolar categorias para a esquerda">←</button>
            <button class="carousel-button" type="button" data-category-scroll="1" aria-label="Rolar categorias para a direita">→</button>
          </div>
        </div>
        <div class="category-carousel" aria-label="Categorias da loja">
          <div class="category-track" data-category-track>${categoryDefinitions.map(categoryCard).join("")}</div>
        </div>
        <p class="carousel-hint">Use as setas ou deslize para explorar as categorias.</p>
      </section>
      <section id="produtos" aria-labelledby="products-title">
        <div class="section-heading">
          <div><p class="eyebrow">${categoryFilter ? "Categoria selecionada" : "Seleção Vértice"}</p><h2 id="products-title">${categoryFilter ? escapeHtml(categoryFilter) : "Tecnologia para o seu dia"}</h2></div>
          ${categoryFilter ? `<button class="button button-quiet" type="button" data-category-filter="">Ver todos os produtos</button>` : ""}
        </div>
        <div class="product-grid">${visibleProducts.length ? visibleProducts.map(productCard).join("") : `<p class="empty-products">Nenhum produto encontrado nesta categoria.</p>`}</div>
      </section>
      <section class="purchase-steps" aria-labelledby="steps-title">
        <div class="section-heading">
          <div><p class="eyebrow">Uma compra simples começa com clareza</p><h2 id="steps-title">Do catálogo ao seu pedido</h2></div>
        </div>
        <div class="steps-grid">
          <article class="step-card"><span>01</span><h3>Escolha seu produto</h3><p>Consulte as fotos, o preço e a disponibilidade exibida na loja.</p></article>
          <article class="step-card"><span>02</span><h3>Confira o carrinho</h3><p>O estoque é verificado novamente ao registrar o pedido.</p></article>
          <article class="step-card"><span>03</span><h3>Acompanhe o pedido</h3><p>Use o código recebido para abrir a página de acompanhamento.</p></article>
        </div>
      </section>
      <section id="sobre" class="value-section">
        <div><p class="eyebrow">Vértice Logística &amp; Varejo</p><h2>Escolhas inteligentes. Atendimento próximo.</h2><p>Uma seleção prática de tecnologia, com informações claras para você comprar com tranquilidade.</p></div>
        <div class="value-points">
          <div class="value-point"><strong>Estoque atualizado</strong><span>Disponibilidade consultada no servidor.</span></div>
          <div class="value-point"><strong>Compra acompanhável</strong><span>Consulte o andamento com seu número de pedido.</span></div>
          <div class="value-point"><strong>Produtos selecionados</strong><span>Cabos, escritório e tecnologia no mesmo lugar.</span></div>
          <div class="value-point"><strong>Checkout simples</strong><span>Escolha Pix, cartão ou boleto no pedido demonstrativo.</span></div>
        </div>
      </section>
      <section id="rastrear" class="tracking-card">
        <p class="eyebrow">Acompanhe sua compra</p>
        <h2 class="page-title">Onde está meu pedido?</h2>
        <p>Digite o código do pedido para consultar os detalhes e o status.</p>
        <form class="tracking-form" data-track-form>
          <input name="order_id" aria-label="Código do pedido" placeholder="Ex.: código do pedido" required>
          <button class="button button-primary" type="submit">Consultar pedido</button>
        </form>
      </section>
    </div>`;
  startCategoryCarousel();
}

function renderProduct(productId) {
  const product = productById(productId);
  if (!product) {
    app.innerHTML = `<div class="page-shell"><section class="empty-state"><h1>Produto não encontrado</h1><p>Este produto não está no catálogo no momento.</p><a class="button button-primary" href="/">Voltar à loja</a></section></div>`;
    return;
  }
  const stock = stockLabel(product.stock);
  selectedQuantity = 1;
  app.innerHTML = `
    <div class="page-shell detail-wrap">
      <div class="breadcrumb"><a href="/">Início</a> &nbsp;›&nbsp; ${escapeHtml(product.category)} &nbsp;›&nbsp; ${escapeHtml(product.name)}</div>
      <section class="detail-card">
        <div class="product-art visual-${escapeHtml(product.visual)} ${product.image_path ? "product-art-photo" : ""}">${productPhoto(product)}</div>
        <div class="detail-info">
          <div class="product-category">${escapeHtml(product.category)}</div>
          <h1>${escapeHtml(product.name)}</h1>
          <p>${escapeHtml(product.description)}</p>
          <div class="price">${formatPrice(product.price_cents)}</div>
          <div class="stock-pill ${stock.className}">${escapeHtml(stock.text)}</div>
          <div class="detail-actions">
            <div class="quantity-control" aria-label="Quantidade">
              <button type="button" data-quantity="-1" aria-label="Diminuir quantidade">−</button>
              <span data-selected-quantity>1</span>
              <button type="button" data-quantity="1" aria-label="Aumentar quantidade" ${product.stock === 0 ? "disabled" : ""}>+</button>
            </div>
            <button type="button" class="button button-primary" data-add="${escapeHtml(product.id)}" ${product.stock === 0 ? "disabled" : ""}>Adicionar ao carrinho</button>
          </div>
          <div class="delivery-note">O estoque é verificado novamente ao finalizar o pedido. A confirmação de pagamento e o envio ainda não estão conectados nesta demonstração.</div>
        </div>
      </section>
    </div>`;
}

async function renderOrder(orderId) {
  app.innerHTML = `<div class="page-shell"><div class="loading-state">Buscando seu pedido...</div></div>`;
  try {
    const returnedPaymentId = new URLSearchParams(location.search).get("payment_id");
    const paymentQuery = returnedPaymentId ? `?payment_id=${encodeURIComponent(returnedPaymentId)}` : "";
    const response = await fetchApi(`/api/orders/${encodeURIComponent(orderId)}${paymentQuery}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível encontrar este pedido.");
    const order = data.order;
    const itemSummary = data.items.map((item) => `${item.product_name} × ${item.quantity}`).join("\n");
    const trackingMessage = ["localhost", "127.0.0.1", "::1"].includes(location.hostname)
      ? `Guarde este código para acompanhar o pedido: ${order.id}.`
      : `Acompanhe o pedido: ${location.origin}/pedido/${encodeURIComponent(order.id)}`;
    const customerMessage = [
      `Olá! Recebemos seu pedido ${order.id} na Vértice.`,
      "O pagamento ainda aguarda confirmação; avisaremos quando houver atualização.",
      trackingMessage,
    ].join("\n\n");
    const sellerMessage = [
      `NOVO PEDIDO VÉRTICE — ${order.id}`,
      itemSummary,
      `Total: ${formatPrice(order.total_cents)}`,
      `Pagamento escolhido: ${order.payment_method}`,
      "Status: aguardando confirmação de pagamento. Favor aguardar a confirmação antes de separar e enviar.",
    ].join("\n\n");
    const customerWhatsAppUrl = `https://wa.me/${data.whatsapp.customer}?text=${encodeURIComponent(customerMessage)}`;
    const sellerWhatsAppUrl = `https://wa.me/${data.whatsapp.seller}?text=${encodeURIComponent(sellerMessage)}`;
    app.innerHTML = `
      <div class="page-shell"><section class="order-card">
        <p class="eyebrow">Acompanhe sua compra</p>
        <h1>Pedido recebido!</h1>
        <p>Guarde este código para consultar o pedido novamente.</p>
        <div class="order-topline"><span><strong>Código:</strong> <span class="order-status">${escapeHtml(order.id)}</span></span><span class="order-status">${escapeHtml(order.status)}</span></div>
        <div class="order-lines">${data.items.map((item) => `<div class="order-line"><span>${escapeHtml(item.product_name)} × ${item.quantity}</span><strong>${formatPrice(item.unit_price_cents * item.quantity)}</strong></div>`).join("")}</div>
        <div class="order-line"><span>Pagamento escolhido</span><span>${escapeHtml(order.payment_method)}</span></div>
        <div class="order-line"><span>Data do pedido</span><span>${escapeHtml(new Date(`${order.created_at.replace(" ", "T")}Z`).toLocaleString("pt-BR"))}</span></div>
        <div class="order-total"><span>Total</span><span>${formatPrice(order.total_cents)}</span></div>
        ${order.payment_status === "demo"
          ? `<div class="demo-notice"><strong>Modo demonstração:</strong> nenhum pagamento foi processado; nenhum aviso automático foi enviado.</div>`
          : `<div class="demo-notice">${order.payment_status === "approved"
            ? "<strong>Pagamento confirmado pelo Mercado Pago.</strong> A atualização do pedido foi registrada."
            : "<strong>Pagamento ainda não confirmado.</strong> O armazém deve aguardar uma confirmação do Mercado Pago antes de separar ou enviar o pedido."}</div>`}
        ${order.payment_status === "demo" || !integrationStatus.whatsapp.configured ? `<div class="whatsapp-actions">
          <a class="button button-whatsapp" href="${customerWhatsAppUrl}" target="_blank" rel="noopener noreferrer">Avisar cliente pelo WhatsApp</a>
          <a class="button button-secondary" href="${sellerWhatsAppUrl}" target="_blank" rel="noopener noreferrer">Preparar aviso para o armazém</a>
        </div>` : `<p class="finance-footnote">Mensagens automáticas dependem dos modelos aprovados e das preferências de contato configuradas no WhatsApp Business.</p>`}
        <a class="button button-secondary" href="/">Voltar à loja</a>
      </section></div>`;
  } catch (error) {
    app.innerHTML = `<div class="page-shell"><section class="empty-state"><h1>Não encontramos esse pedido</h1><p>${escapeHtml(error.message)}</p><a class="button button-primary" href="/#rastrear">Tentar novamente</a></section></div>`;
  }
}

function renderFinanceLogin(message = "") {
  app.innerHTML = `
    <div class="page-shell"><section class="finance-card finance-login">
      <p class="eyebrow">Acesso restrito</p><h1>Área da empresa</h1>
      <p>Entre com a senha definida pela empresa para consultar a demonstração de margem por produto.</p>
      <form data-finance-login>
        <div class="form-field"><label for="finance-password">Senha de acesso</label><input id="finance-password" name="password" type="password" autocomplete="current-password" required></div>
        ${message ? `<p class="checkout-error" role="alert">${escapeHtml(message)}</p>` : ""}
        <button class="button button-primary button-block" type="submit" style="margin-top:17px">Entrar na área financeira</button>
      </form>
      <p class="finance-footnote" style="margin-top:18px">Os custos e as margens são hipotéticos. A senha é configurada no ambiente do servidor; nenhuma credencial padrão é criada.</p>
    </section></div>`;
}

async function renderFinance() {
  app.innerHTML = `<div class="page-shell"><div class="loading-state">Verificando acesso...</div></div>`;
  try {
    const response = await fetchApi("/api/finance/data");
    if (response.status === 401) {
      renderFinanceLogin();
      return;
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível carregar a área financeira.");
    const rows = data.products.map((product) => `
      <tr>
        <td>${escapeHtml(product.name)}</td><td>${product.units_sold}</td>
        <td>${formatPrice(product.revenue_cents)}</td><td>${formatPrice(product.cost_cents)}</td>
        <td class="${product.profit_cents >= 0 ? "profit-positive" : "profit-negative"}">${formatPrice(product.profit_cents)}</td>
        <td>${product.stock}</td>
      </tr>`).join("");
    app.innerHTML = `
      <div class="page-shell"><section class="finance-card">
        <div class="section-heading"><div><p class="eyebrow">Visão interna</p><h1>Resultado por produto</h1></div><button class="button button-secondary" data-finance-logout type="button">Sair</button></div>
        <p>Receita, custo estimado e lucro bruto calculados a partir dos pedidos registrados nesta demonstração.</p>
        <div class="demo-notice">Dados hipotéticos para treinamento. Antes de usar em produção, conecte custos reais, regras fiscais e os sistemas financeiros da empresa.</div>
        <div class="finance-table-wrap"><table class="finance-table">
          <thead><tr><th>Produto</th><th>Vendidos</th><th>Receita</th><th>Custo</th><th>Lucro bruto</th><th>Estoque</th></tr></thead>
          <tbody>${rows}</tbody>
        </table></div>
        <p class="finance-footnote">Lucro bruto estimado = receita dos pedidos − custo hipotético de aquisição. Não inclui frete, impostos, taxas ou despesas operacionais.</p>
      </section></div>`;
  } catch (error) {
    app.innerHTML = `<div class="page-shell"><section class="empty-state"><h1>Área financeira indisponível</h1><p>${escapeHtml(error.message)}</p><a class="button button-secondary" href="/">Voltar à loja</a></section></div>`;
  }
}

async function renderRoute() {
  const path = decodeURI(location.pathname);
  if (path.startsWith("/produto/")) {
    renderProduct(path.slice("/produto/".length));
  } else if (path.startsWith("/pedido/")) {
    await renderOrder(path.slice("/pedido/".length));
  } else if (path === "/empresa") {
    await renderFinance();
  } else {
    renderHome();
    if (location.hash) requestAnimationFrame(() => document.querySelector(location.hash)?.scrollIntoView());
  }
}

function navigate(path) {
  history.pushState({}, "", path);
  renderRoute();
  window.scrollTo(0, 0);
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  document.querySelector(".toast-region").append(toast);
  window.setTimeout(() => toast.remove(), 3200);
}

function addToCart(productId, quantity = 1) {
  const product = productById(productId);
  if (!product) return;
  const cart = getCart();
  const existing = cart.find((item) => item.product_id === productId);
  const nextQuantity = (existing?.quantity || 0) + quantity;
  if (nextQuantity > product.stock) {
    showToast(`Estoque disponível: ${product.stock} unidade(s).`);
    return;
  }
  if (existing) existing.quantity = nextQuantity;
  else cart.push({ product_id: productId, quantity });
  saveCart(cart);
  showToast(`${product.name} adicionado ao carrinho.`);
}

function setDrawerOpen(open) {
  cartDrawer.classList.toggle("open", open);
  cartDrawer.setAttribute("aria-hidden", String(!open));
  overlay.hidden = !open;
  document.body.style.overflow = open ? "hidden" : "";
  if (open) renderCart();
}

function renderCart() {
  const cart = getCart();
  const lines = cart.map((item) => ({ ...item, product: productById(item.product_id) })).filter((item) => item.product);
  const total = lines.reduce((sum, item) => sum + item.product.price_cents * item.quantity, 0);
  cartDrawer.innerHTML = `
    <div class="drawer-heading"><h2>Seu carrinho <span class="cart-count">${lines.reduce((sum, item) => sum + item.quantity, 0)}</span></h2><button class="close-button" data-close-cart aria-label="Fechar carrinho">×</button></div>
    ${lines.length ? `
      <div>${lines.map((item) => `<div class="cart-line">
        <span class="cart-line-icon">${escapeHtml(item.product.icon)}</span>
        <span><span class="cart-line-name">${escapeHtml(item.product.name)}</span><br><span class="cart-line-price">${formatPrice(item.product.price_cents)}</span></span>
        <span class="cart-line-actions"><button data-cart-change="${escapeHtml(item.product.id)}" data-delta="-1" aria-label="Remover unidade">−</button><span>${item.quantity}</span><button data-cart-change="${escapeHtml(item.product.id)}" data-delta="1" aria-label="Adicionar unidade">+</button></span>
      </div>`).join("")}</div>
      <div class="cart-total"><span>Subtotal</span><span>${formatPrice(total)}</span></div>
      <p class="finance-footnote">O estoque será confirmado novamente ao concluir o pedido.</p>
      <button class="button button-primary button-block" data-start-checkout>Continuar para pagamento</button>
    ` : `<div class="cart-empty">Seu carrinho ainda está vazio.<br><br><a class="subtle-link" href="/">Descobrir produtos →</a></div>`}`;
}

function openCheckout() {
  const lines = getCart().map((item) => ({ ...item, product: productById(item.product_id) })).filter((item) => item.product);
  if (!lines.length) return;
  const total = lines.reduce((sum, item) => sum + item.product.price_cents * item.quantity, 0);
  checkoutAttemptKey = crypto.randomUUID();
  const paymentConfiguration = integrationStatus.payments;
  const livePayments = paymentConfiguration.configured && paymentConfiguration.ready;
  const paymentUnavailable = paymentConfiguration.mode === "unavailable"
    || (paymentConfiguration.configured && !paymentConfiguration.ready);
  const checkoutButtonText = paymentUnavailable
    ? "Checkout real indisponível"
    : livePayments
      ? "Continuar para pagamento seguro"
      : "Confirmar pedido fictício";
  checkoutDialog.innerHTML = `
    <div class="checkout-heading"><div><h2 id="checkout-title">Finalizar pedido</h2><p>Preencha os dados de contato e entrega.</p></div><button class="close-button" data-close-checkout aria-label="Fechar">×</button></div>
    <form data-checkout-form>
      <div class="form-field"><label for="customer-name">Nome completo</label><input id="customer-name" name="name" autocomplete="name" required maxlength="200"></div>
      <div class="form-field"><label for="customer-email">E-mail</label><input id="customer-email" name="email" type="email" autocomplete="email" required maxlength="200"></div>
      <div class="form-field"><label for="customer-phone">Telefone</label><input id="customer-phone" name="phone" type="tel" autocomplete="tel" required maxlength="30"></div>
      <div class="form-field"><label for="customer-postal">CEP</label><input id="customer-postal" name="postal_code" autocomplete="postal-code" required maxlength="12"></div>
      <div class="form-field"><label for="customer-address">Endereço de entrega</label><input id="customer-address" name="address" autocomplete="street-address" required maxlength="200" placeholder="Rua, número, complemento, cidade/UF"></div>
      <div class="field-label" style="margin-top:19px">Forma de pagamento</div>
      <div class="payment-options">
        <label class="payment-option"><input type="radio" name="payment_method" value="pix" required checked> Pix</label>
        <label class="payment-option"><input type="radio" name="payment_method" value="card"> Cartão</label>
        <label class="payment-option"><input type="radio" name="payment_method" value="boleto"> Boleto</label>
      </div>
      <div class="checkout-summary">${lines.map((item) => `${escapeHtml(item.product.name)} × ${item.quantity}`).join("<br>")}<br><strong>Total: ${formatPrice(total)}</strong></div>
      <label class="whatsapp-consent"><input type="checkbox" name="whatsapp_opt_in"><span>Aceito receber atualizações deste pedido por WhatsApp da Vértice. Posso cancelar essa autorização quando quiser.</span></label>
      ${livePayments
        ? `<div class="checkout-provider-note">O pagamento será processado com segurança pelo Checkout Pro do Mercado Pago. O site não recebe dados do seu cartão.</div>`
        : paymentUnavailable
          ? `<div class="checkout-error" role="alert">${escapeHtml(paymentConfiguration.error || "Configure a URL HTTPS pública e o segredo do webhook para habilitar o pagamento.")} Nenhum pedido fictício será criado com o checkout real configurado.</div>`
          : `<div class="demo-notice">Modo de demonstração: nenhum pagamento real será cobrado e os avisos automáticos de WhatsApp estão desativados.</div>`}
      <p class="checkout-error" data-checkout-error role="alert" hidden></p>
      <button class="button button-primary button-block" type="submit" style="margin-top:16px" ${paymentUnavailable ? "disabled" : ""}>${checkoutButtonText}</button>
    </form>`;
  setDrawerOpen(false);
  checkoutDialog.showModal();
}

document.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const categoryFilter = target.closest("[data-category-filter]");
  if (categoryFilter) {
    renderHome(categoryFilter.dataset.categoryFilter || null);
    document.querySelector("#produtos").scrollIntoView({ behavior: "smooth" });
    return;
  }
  const categoryScroll = target.closest("[data-category-scroll]");
  if (categoryScroll) {
    const track = document.querySelector("[data-category-track]");
    const card = track?.querySelector(".category-card");
    if (track && card) {
      const gap = Number.parseFloat(getComputedStyle(track).columnGap) || 0;
      track.scrollBy({
        left: Number(categoryScroll.dataset.categoryScroll) * (card.getBoundingClientRect().width + gap),
        behavior: "smooth",
      });
    }
    return;
  }
  const addButton = target.closest("[data-add]");
  if (addButton) {
    addToCart(addButton.dataset.add, addButton.closest(".detail-card") ? selectedQuantity : 1);
    return;
  }
  if (target.closest("[data-open-cart]")) {
    setDrawerOpen(true);
    return;
  }
  if (target.closest("[data-close-cart]") || target === overlay) {
    setDrawerOpen(false);
    return;
  }
  if (target.closest("[data-start-checkout]")) {
    openCheckout();
    return;
  }
  const cartChange = target.closest("[data-cart-change]");
  if (cartChange) {
    const cart = getCart();
    const item = cart.find((line) => line.product_id === cartChange.dataset.cartChange);
    if (item) {
      item.quantity += Number(cartChange.dataset.delta);
      if (item.quantity <= 0) cart.splice(cart.indexOf(item), 1);
      else if (item.quantity > (productById(item.product_id)?.stock || 0)) {
        item.quantity = productById(item.product_id)?.stock || 0;
        showToast(`Estoque disponível: ${item.quantity} unidade(s).`);
      }
      saveCart(cart);
      renderCart();
    }
    return;
  }
  const quantityButton = target.closest("[data-quantity]");
  if (quantityButton) {
    const product = productById(location.pathname.slice("/produto/".length));
    if (!product) return;
    selectedQuantity = Math.min(product.stock, Math.max(1, selectedQuantity + Number(quantityButton.dataset.quantity)));
    document.querySelector("[data-selected-quantity]").textContent = String(selectedQuantity);
    return;
  }
  if (target.closest("[data-close-checkout]")) checkoutDialog.close();
  if (target.closest("[data-finance-logout]")) {
    try {
      await fetchApi("/api/finance/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      renderFinanceLogin("Sessão encerrada.");
    } catch (error) {
      showToast(`Não foi possível encerrar a sessão: ${error.message}`);
    }
  }
});

document.addEventListener("submit", async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (form.matches("[data-track-form]")) {
    event.preventDefault();
    const orderId = new FormData(form).get("order_id").trim();
    if (orderId) navigate(`/pedido/${encodeURIComponent(orderId)}`);
    return;
  }
  if (form.matches("[data-checkout-form]")) {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    const errorBox = form.querySelector("[data-checkout-error]");
    submit.disabled = true;
    submit.textContent = "Registrando pedido...";
    errorBox.hidden = true;
    const formData = new FormData(form);
    const customer = Object.fromEntries(["name", "email", "phone", "postal_code", "address"].map((key) => [key, formData.get(key)]));
    try {
      const response = await fetchApi("/api/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer,
          items: getCart(),
          payment_method: formData.get("payment_method"),
          whatsapp_opt_in: formData.has("whatsapp_opt_in"),
          idempotency_key: checkoutAttemptKey,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Não foi possível registrar o pedido.");
      saveCart([]);
      checkoutDialog.close();
      if (result.checkout_url) {
        window.location.assign(result.checkout_url);
        return;
      }
      window.location.assign(`/pedido/${encodeURIComponent(result.order_id)}`);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.hidden = false;
      const payments = integrationStatus.payments;
      submit.disabled = payments.mode === "unavailable"
        || (payments.configured && !payments.ready);
      submit.textContent = payments.mode === "unavailable" || (payments.configured && !payments.ready)
        ? "Checkout real indisponível"
        : payments.configured
          ? "Continuar para pagamento seguro"
          : "Confirmar pedido fictício";
      if (error.message.includes("Estoque insuficiente")) {
        await refreshProducts();
        renderCart();
      }
    }
    return;
  }
  if (form.matches("[data-finance-login]")) {
    event.preventDefault();
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const response = await fetchApi("/api/finance/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: new FormData(form).get("password") }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Não foi possível entrar.");
      await renderFinance();
    } catch (error) {
      renderFinanceLogin(error.message);
    }
  }
});

document.addEventListener("click", (event) => {
  const link = event.target instanceof Element ? event.target.closest("a") : null;
  if (!link || link.target || link.origin !== location.origin) return;
  const targetUrl = new URL(link.href);
  if (targetUrl.pathname !== location.pathname || targetUrl.hash !== location.hash) {
    event.preventDefault();
    history.pushState({}, "", targetUrl.pathname + targetUrl.search + targetUrl.hash);
    renderRoute();
    if (targetUrl.hash && targetUrl.pathname === "/") {
      requestAnimationFrame(() => document.querySelector(targetUrl.hash)?.scrollIntoView());
    } else {
      window.scrollTo(0, 0);
    }
  }
});

window.addEventListener("popstate", renderRoute);

async function refreshProducts() {
  const [productsResponse, statusResponse] = await Promise.all([
    fetchApi("/api/products"),
    fetchApi("/api/integrations/status"),
  ]);
  if (!productsResponse.ok) throw new Error("Não foi possível atualizar o estoque.");
  if (!statusResponse.ok) {
    const result = await statusResponse.json();
    throw new Error(result.error || "Não foi possível verificar as integrações da loja.");
  }
  const [catalog, status] = await Promise.all([
    productsResponse.json(),
    statusResponse.json(),
  ]);
  products = catalog.products;
  integrationStatus = status;
  updateCartCount();
}

refreshProducts().then(renderRoute).catch((error) => {
  app.innerHTML = `<div class="page-shell"><section class="empty-state"><h1>Não foi possível carregar a loja</h1><p>${escapeHtml(error.message)}</p></section></div>`;
});
