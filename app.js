const tabButtons = document.querySelectorAll('.tab-btn');
const panels = {
  smart: document.getElementById('tab-smart'),
  catalog: document.getElementById('tab-catalog'),
  add: document.getElementById('tab-add'),
  cart: document.getElementById('tab-cart'),
};

const toast = document.getElementById('toast');

const nlpForm = document.getElementById('nlp-form');//captures user queries 
const nlpQuery = document.getElementById('nlp-query');
const useExampleBtn = document.getElementById('use-example');
const nlpOutput = document.getElementById('nlp-output');
const nlpResults = document.getElementById('nlp-results');
const conversationOutput = document.getElementById('conversation-output');

const productList = document.getElementById('product-list');
const catalogCount = document.getElementById('catalog-count');
const catalogSearch = document.getElementById('catalog-search');
const refreshProductsBtn = document.getElementById('refresh-products');

const addForm = document.getElementById('add-form');
const addStatus = document.getElementById('add-status');

const cartList = document.getElementById('cart-list');
const cartCount = document.getElementById('cart-count');

let catalog = [];
let cart = [];

function showToast(msg, type = 'success') {
  toast.textContent = msg;
  toast.className = type;
  toast.show();
  setTimeout(() => toast.close(), 1500);
}

function switchTab(tabId) {
  for (const [id, panel] of Object.entries(panels)) {
    panel.classList.toggle('active', id === tabId);
  }
  tabButtons.forEach((btn) => btn.classList.toggle('active', btn.dataset.tab === tabId));
}

tabButtons.forEach((btn) => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

function createProductCard(item, includeAddToCart = false) {
  return `
    <article class="card">
      <h4>${item.name}</h4>
      <p>${item.description}</p>
      <strong>$${Number(item.price).toFixed(2)}</strong>
      ${
        includeAddToCart
          ? `<div class="card-actions"><button data-add-cart="${item.id || `${item.name}-${item.price}`}">Add to Cart</button></div>`
          : ''
      }
    </article>
  `;
}

function renderProducts(target, items, includeAddToCart = false) {
  if (!items.length) {
    target.innerHTML = '<p class="hint">No products found.</p>';
    return;
  }

  target.innerHTML = items
    .map((item) => createProductCard(item, includeAddToCart))
    .join('');
}

function addToCart(item) {
  cart.push(item);
  renderCart();
  showToast(`${item.name} added to cart`);
}

function bindAddToCart(container, sourceItems) {
  container.querySelectorAll('[data-add-cart]').forEach((button) => {
    button.addEventListener('click', () => {
      const key = button.getAttribute('data-add-cart');
      const selected = sourceItems.find(
        (p) => String(p.id || `${p.name}-${p.price}`) === key,
      );
      if (selected) addToCart(selected);
    });
  });
}

function renderCart() {
  cartCount.textContent = `${cart.length} item${cart.length === 1 ? '' : 's'}`;
  if (!cart.length) {
    cartList.innerHTML = '<p class="hint">Your cart is empty.</p>';
    return;
  }

  renderProducts(cartList, cart, false);
}

async function fetchProducts() {
  const res = await fetch('/products');
  if (!res.ok) throw new Error('Could not fetch catalog');
  catalog = await res.json();
  applyCatalogFilter();
}

function applyCatalogFilter() {
  const term = catalogSearch.value.trim().toLowerCase();
  const filtered = term
    ? catalog.filter((p) => `${p.name} ${p.description}`.toLowerCase().includes(term))
    : catalog;

  catalogCount.textContent = `${filtered.length} / ${catalog.length} items`;
  renderProducts(productList, filtered, true);
  bindAddToCart(productList, filtered);
}

function renderRecommendations(results) {
  renderProducts(nlpResults, results, true);
  bindAddToCart(nlpResults, results);
}

async function runNlpSearch(query) {
  nlpOutput.textContent = 'Searching...';
  conversationOutput.textContent = 'Thinking about your request...';
  nlpResults.innerHTML = '<p class="hint">Loading recommendations...</p>';

  const res = await fetch(`/nlp_search?query=${encodeURIComponent(query)}`);
  if (!res.ok) throw new Error('NLP endpoint failed');
  const data = await res.json();

  // show response in individual boxes style + simplified query + interpreted JSON
  nlpOutput.textContent = JSON.stringify(
    {
      simplified_query: data.simplified_query,
      filters: data.llm_output,
    },
    null,
    2,
  );
  renderRecommendations(data.results || []);
  conversationOutput.textContent = data.conversation_output || 'No conversational response available.';

  if (data.suggestions) showToast(data.suggestions, 'success');
}

nlpForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const query = nlpQuery.value.trim();
  if (!query) return;

  try {
    await runNlpSearch(query);
  } catch (error) {
    nlpOutput.textContent = `Error: ${String(error)}`;
    nlpResults.innerHTML = '<p class="hint">Try again.</p>';
    conversationOutput.textContent = 'Could not process that request right now.';
    showToast('Search failed', 'error');
  }
});

useExampleBtn.addEventListener('click', () => {
  nlpQuery.value = 'Sugar-free chocolates under 500';
  nlpForm.requestSubmit();
});

catalogSearch.addEventListener('input', applyCatalogFilter);
refreshProductsBtn.addEventListener('click', async () => {
  try {
    await fetchProducts();
    showToast('Catalog refreshed');
  } catch {
    showToast('Refresh failed', 'error');
  }
});

addForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  addStatus.textContent = 'Saving product...';

  const payload = {
    name: document.getElementById('name').value,
    description: document.getElementById('description').value,
    price: Number(document.getElementById('price').value),
  };

  try {
    const res = await fetch('/products', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());

    addStatus.textContent = '✅ Product saved';
    addForm.reset();
    await fetchProducts();
    showToast('Product added');
    switchTab('catalog');
  } catch (error) {
    addStatus.textContent = `❌ ${String(error)}`;
    showToast('Add failed', 'error');
  }
});

async function init() {
  switchTab('smart');
  renderCart();
  try {
    await fetchProducts();
  } catch {
    productList.innerHTML = '<p class="hint">Catalog unavailable.</p>';
  }
}

init();
