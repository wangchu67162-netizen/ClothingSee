/* 云裳商城 — 原生 JS（无框架、无 CDN、无外部请求）。
   页面通过 <body data-page="home|product|checkout|success"> 分发逻辑。 */
(function () {
  'use strict';

  var API = '/demo-mall/api';

  // ---------------------------------------------------------------- helpers
  function qs(selector, root) {
    return (root || document).querySelector(selector);
  }

  function qsa(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }

  function formatPrice(value) {
    var number = Number(value);
    if (!isFinite(number)) return '—';
    return '¥' + number.toLocaleString('zh-CN', { maximumFractionDigits: 2 });
  }

  function errorDetail(payload, fallback) {
    if (!payload) return fallback;
    if (typeof payload.detail === 'string') return payload.detail;
    if (Array.isArray(payload.detail)) {
      return payload.detail.map(function (item) { return item.msg || ''; }).filter(Boolean).join('；') || fallback;
    }
    if (typeof payload.message === 'string') return payload.message;
    return fallback;
  }

  function api(path) {
    return fetch(API + path, { headers: { Accept: 'application/json' } }).then(function (response) {
      return response.json().catch(function () { return null; }).then(function (payload) {
        if (!response.ok) {
          throw new Error(errorDetail(payload, '请求失败（' + response.status + '）'));
        }
        return payload;
      });
    });
  }

  function bindImageFallback(root) {
    qsa('img', root || document).forEach(function (img) {
      img.addEventListener('error', function () {
        img.classList.add('is-missing');
        img.setAttribute('alt', '图片暂缺');
        img.removeAttribute('src');
      }, { once: true });
    });
  }

  function showError(element, message) {
    if (!element) return;
    element.textContent = message;
    element.hidden = false;
  }

  function hideError(element) {
    if (!element) return;
    element.hidden = true;
    element.textContent = '';
  }

  // ------------------------------------------------------------------- home
  function initHome() {
    var grid = qs('#mall-grid');
    var empty = qs('#mall-empty');
    var errorBox = qs('#mall-error');
    var count = qs('#mall-result-count');
    var title = qs('#mall-result-title');
    var form = qs('#mall-search-form');
    var input = qs('#mall-search');
    var timer = null;
    var requestSeq = 0;

    var initial = new URLSearchParams(window.location.search).get('q') || '';
    input.value = initial;

    function cardHtml(product) {
      return '' +
        '<a class="mall-card" data-testid="mall-product-card" data-product-id="' + esc(product.id) + '" href="product.html?id=' + encodeURIComponent(product.id) + '">' +
          '<div class="mall-card-media">' +
            '<img src="' + esc(product.image) + '" alt="' + esc(product.name) + '" loading="lazy" />' +
            '<span class="mall-card-tag">' + esc(product.category) + '</span>' +
          '</div>' +
          '<div class="mall-card-body">' +
            '<h3 data-testid="mall-product-name">' + esc(product.name) + '</h3>' +
            '<p class="mall-card-sub">' + esc(product.subtitle || product.fit || '本季精选') + '</p>' +
            '<div class="mall-card-foot">' +
              '<span class="mall-price">' + formatPrice(product.price) + '</span>' +
              '<span class="mall-buy-hint">立即购买</span>' +
            '</div>' +
          '</div>' +
        '</a>';
    }

    function load(keyword) {
      var seq = ++requestSeq;
      hideError(errorBox);
      grid.setAttribute('aria-busy', 'true');
      api('/products' + (keyword ? '?q=' + encodeURIComponent(keyword) : ''))
        .then(function (data) {
          if (seq !== requestSeq) return;
          var items = (data && data.items) || [];
          grid.innerHTML = items.map(cardHtml).join('');
          bindImageFallback(grid);
          empty.hidden = items.length > 0;
          count.textContent = '共 ' + items.length + ' 件';
          title.textContent = keyword ? '「' + keyword + '」的搜索结果' : '本季精选';
          grid.setAttribute('aria-busy', 'false');
          try {
            var url = new URL(window.location.href);
            if (keyword) url.searchParams.set('q', keyword);
            else url.searchParams.delete('q');
            window.history.replaceState(null, '', url);
          } catch (err) { /* ignore */ }
        })
        .catch(function (error) {
          if (seq !== requestSeq) return;
          grid.innerHTML = '';
          grid.setAttribute('aria-busy', 'false');
          count.textContent = '';
          showError(errorBox, error.message || '商品加载失败，请稍后重试。');
        });
    }

    if (form) {
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        if (timer) { clearTimeout(timer); timer = null; }
        load(input.value.trim());
      });
    }
    if (input) {
      input.addEventListener('input', function () {
        if (timer) clearTimeout(timer);
        timer = setTimeout(function () { load(input.value.trim()); }, 350);
      });
    }

    load(initial);
  }

  // ---------------------------------------------------------------- product
  function initProduct() {
    var params = new URLSearchParams(window.location.search);
    var productId = Number(params.get('id'));
    var token = params.get('token') || '';
    if (token) {
      try { sessionStorage.setItem('mall_task_token', token); } catch (err) { /* ignore */ }
    }

    var loading = qs('#product-loading');
    var errorBox = qs('#product-error');
    var panel = qs('#product-panel');

    if (!productId) {
      loading.hidden = true;
      showError(errorBox, '缺少商品编号，请返回云裳商城重新选择。');
      return;
    }

    var state = { size: '', color: '', quantity: 1 };

    function renderChips(container, values, kind) {
      container.innerHTML = values.map(function (value, index) {
        return '<button type="button" class="mall-chip' + (index === 0 ? ' is-selected' : '') + '" data-' + kind + '="' + esc(value) + '">' + esc(value) + '</button>';
      }).join('');
      if (values.length) {
        if (kind === 'size') state.size = values[0];
        else state.color = values[0];
      }
      qsa('.mall-chip', container).forEach(function (chip) {
        chip.addEventListener('click', function () {
          qsa('.mall-chip', container).forEach(function (item) { item.classList.remove('is-selected'); });
          chip.classList.add('is-selected');
          if (kind === 'size') state.size = chip.getAttribute('data-size');
          else state.color = chip.getAttribute('data-color');
          hideError(qs('#product-select-error'));
        });
      });
    }

    api('/products/' + encodeURIComponent(productId))
      .then(function (product) {
        loading.hidden = true;
        panel.hidden = false;
        document.title = product.name + ' · 云裳商城';
        qs('#product-crumb').textContent = product.name;
        qs('#product-category').textContent = (product.category || '') + ' · YUNSHANG SELECT';
        qs('#product-title').textContent = product.name;
        qs('#product-subtitle').textContent = product.subtitle || '';
        qs('#product-price').textContent = formatPrice(product.price);
        var original = qs('#product-original');
        if (product.original_price) {
          original.textContent = formatPrice(product.original_price);
        } else {
          original.hidden = true;
        }
        qs('#product-desc').textContent = product.description || '';
        qs('#product-fabric').textContent = product.fabric || '—';
        qs('#product-fit').textContent = product.fit || '—';
        qs('#product-occasion').textContent = product.occasion || '—';
        qs('#product-season').textContent = product.season || '—';
        qs('#product-stock').textContent = (product.stock > 0 ? '现货 ' + product.stock + ' 件' : '暂时售罄');

        var image = qs('#product-image');
        image.src = product.image;
        image.alt = product.name;
        bindImageFallback(panel);

        var thumbs = qs('#product-thumbs');
        var gallery = (product.gallery && product.gallery.length ? product.gallery : [product.image]).slice(0, 4);
        thumbs.innerHTML = gallery.map(function (src, index) {
          return '<button type="button" class="mall-thumb' + (index === 0 ? ' is-selected' : '') + '" aria-label="查看商品图 ' + (index + 1) + '">' +
            '<img src="' + esc(src) + '" alt="" loading="lazy" /></button>';
        }).join('');
        qsa('.mall-thumb', thumbs).forEach(function (thumb, index) {
          thumb.addEventListener('click', function () {
            qsa('.mall-thumb', thumbs).forEach(function (item) { item.classList.remove('is-selected'); });
            thumb.classList.add('is-selected');
            image.src = gallery[index];
          });
        });
        bindImageFallback(thumbs);

        renderChips(qs('#product-colors'), product.colors || [], 'color');
        renderChips(qs('#product-sizes'), product.sizes || [], 'size');

        var qtyInput = qs('#mall-qty');
        function clampQty(next) {
          var value = Math.max(1, Math.min(10, Number(next) || 1));
          qtyInput.value = String(value);
          state.quantity = value;
        }
        qtyInput.addEventListener('change', function () { clampQty(qtyInput.value); });
        qs('#qty-minus').addEventListener('click', function () { clampQty(Number(qtyInput.value) - 1); });
        qs('#qty-plus').addEventListener('click', function () { clampQty(Number(qtyInput.value) + 1); });

        var buyButton = qs('#mall-buy-now');
        if (!(product.stock > 0)) {
          buyButton.disabled = true;
          buyButton.textContent = '暂时售罄';
        }
        buyButton.addEventListener('click', function () {
          var selectError = qs('#product-select-error');
          if ((product.sizes || []).length && !state.size) {
            showError(selectError, '请选择尺码。');
            return;
          }
          if ((product.colors || []).length && !state.color) {
            showError(selectError, '请选择颜色。');
            return;
          }
          hideError(selectError);
          var link = 'checkout.html?id=' + encodeURIComponent(product.id) +
            '&size=' + encodeURIComponent(state.size) +
            '&color=' + encodeURIComponent(state.color) +
            '&qty=' + encodeURIComponent(state.quantity);
          var storedToken = '';
          try { storedToken = sessionStorage.getItem('mall_task_token') || ''; } catch (err) { storedToken = ''; }
          var effectiveToken = token || storedToken;
          if (effectiveToken) link += '&token=' + encodeURIComponent(effectiveToken);
          window.location.href = link;
        });
      })
      .catch(function (error) {
        loading.hidden = true;
        showError(errorBox, error.message || '商品加载失败，请稍后重试。');
      });
  }

  // --------------------------------------------------------------- checkout
  function initCheckout() {
    var params = new URLSearchParams(window.location.search);
    var productId = Number(params.get('id'));
    var size = params.get('size') || '';
    var color = params.get('color') || '';
    var quantity = Math.max(1, Math.min(10, Number(params.get('qty')) || 1));
    var token = params.get('token') || '';
    try {
      if (!token) token = sessionStorage.getItem('mall_task_token') || '';
      if (token) sessionStorage.setItem('mall_task_token', token);
    } catch (err) { /* ignore */ }

    var loading = qs('#checkout-loading');
    var fatal = qs('#checkout-fatal');
    var layout = qs('#checkout-layout');
    var errorBox = qs('#checkout-error');
    var submit = qs('#mall-place-order');
    var product = null;

    if (!productId) {
      loading.hidden = true;
      showError(fatal, '缺少商品编号，请返回云裳商城重新选择。');
      return;
    }

    qs('#checkout-back').href = 'product.html?id=' + encodeURIComponent(productId);

    api('/products/' + encodeURIComponent(productId))
      .then(function (data) {
        product = data;
        loading.hidden = true;
        layout.hidden = false;
        document.title = '结算 · ' + product.name + ' · 云裳商城';

        qs('#checkout-image').src = product.image;
        qs('#checkout-image').alt = product.name;
        bindImageFallback(layout);
        qs('#checkout-name').textContent = product.name;
        qs('#checkout-variant').textContent = [color || '默认颜色', size || '默认尺码'].join(' / ');
        qs('#checkout-price').textContent = formatPrice(product.price) + ' × ' + quantity;
        qs('#checkout-qty').textContent = String(quantity);
        qs('#checkout-total').textContent = formatPrice(Number(product.price) * quantity);
      })
      .catch(function (error) {
        loading.hidden = true;
        showError(fatal, error.message || '订单商品加载失败，请返回商城重试。');
      });

    var form = qs('#checkout-form');
    if (!form) return;

    form.addEventListener('submit', function (event) {
      event.preventDefault();
      hideError(errorBox);
      if (!product) {
        showError(errorBox, '商品信息尚未加载完成，请稍候。');
        return;
      }

      var name = qs('#ship-name').value.trim();
      var phone = qs('#ship-phone').value.trim();
      var address = qs('#ship-address').value.trim();
      if (!name) { showError(errorBox, '请填写收货人姓名。'); qs('#ship-name').focus(); return; }
      if (!/^[0-9+\-\s]{5,24}$/.test(phone)) { showError(errorBox, '请填写有效的手机号（5–24 位数字）。'); qs('#ship-phone').focus(); return; }
      if (address.length < 3) { showError(errorBox, '请填写完整的收货地址。'); qs('#ship-address').focus(); return; }

      if (!token) {
        showError(errorBox, '缺少任务令牌：请从「衣见 AI 购物助理」发起下单，或返回平台完成购买。');
        return;
      }

      submit.disabled = true;
      submit.textContent = '正在提交…';

      fetch(API + '/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({
          task_token: token,
          product_id: product.id,
          size: size,
          color: color,
          quantity: quantity,
          customer: { name: name, phone: phone, address: address },
        }),
      })
        .then(function (response) {
          return response.json().catch(function () { return null; }).then(function (payload) {
            if (!response.ok) {
              throw new Error(errorDetail(payload, '下单失败，请稍后重试。'));
            }
            if (!payload || !payload.order_no) {
              throw new Error('商城未返回订单号，请稍后重试。');
            }
            var target = 'success.html?order_no=' + encodeURIComponent(payload.order_no) +
              '&total=' + encodeURIComponent(payload.total);
            window.location.href = target;
          });
        })
        .catch(function (error) {
          // 失败绝不跳转成功页，也不显示“下单成功”。
          showError(errorBox, error.message || '网络异常，未能连接云裳商城，请稍后重试。');
          submit.disabled = false;
          submit.textContent = '提交订单（模拟支付）';
        });
    });
  }

  // ---------------------------------------------------------------- success
  function initSuccess() {
    var params = new URLSearchParams(window.location.search);
    var orderNo = (params.get('order_no') || '').trim();
    var total = params.get('total');

    var orderNoElement = qs('#order-no');
    var totalElement = qs('#order-total');
    var missing = qs('#success-missing');

    if (orderNo) {
      orderNoElement.textContent = orderNo;
    } else {
      orderNoElement.textContent = '—';
      if (missing) missing.hidden = false;
    }

    if (total && isFinite(Number(total))) {
      totalElement.textContent = formatPrice(Number(total));
    } else {
      totalElement.textContent = '—';
    }
  }

  // ---------------------------------------------------------------- dispatch
  document.addEventListener('DOMContentLoaded', function () {
    var page = document.body.getAttribute('data-page');
    if (page === 'home') initHome();
    else if (page === 'product') initProduct();
    else if (page === 'checkout') initCheckout();
    else if (page === 'success') initSuccess();
  });
})();
