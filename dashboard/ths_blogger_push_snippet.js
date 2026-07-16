(function () {
  const ENDPOINT = "http://127.0.0.1:8765/api/blogger/import";
  const SOURCE = "ths_homepage_browser";
  const seen = new Set();

  function textOf(node) {
    return (node && node.innerText ? node.innerText : "").replace(/\s+/g, " ").trim();
  }

  function textKey(text) {
    let hash = 0;
    for (let i = 0; i < text.length; i += 1) hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
    return `text:${Math.abs(hash)}`;
  }

  function visible(node) {
    const rect = node.getBoundingClientRect && node.getBoundingClientRect();
    return rect && rect.width > 20 && rect.height > 20;
  }

  function extractPosts() {
    const html = document.documentElement.innerHTML;
    const raw = `${location.href}\n${html}`;
    const ids = Array.from(new Set([
      ...Array.from(raw.matchAll(/contentId=([^&#"'<\s]+)/g)).map((m) => m[1]),
      ...Array.from(raw.matchAll(/contentId_([0-9a-z]+)/g)).map((m) => m[1]),
    ]));
    const posts = ids.map((contentId) => ({
      content_id: contentId,
      url: `https://c.10jqka.com.cn/m/post/discussDetail/?contentId=${contentId}`,
      text: textOf(document.body).slice(0, 600),
    }));

    document.querySelectorAll("a[href*='discussDetail'], [data-url*='discussDetail']").forEach((node) => {
      const url = node.href || node.getAttribute("data-url") || "";
      const match = url.match(/contentId=([^&#]+)/) || url.match(/contentId_([0-9a-z]+)/);
      if (!match) return;
      const card = node.closest("article, li, .post-item, .dynamic-item, .content-item, .list-item") || node.parentElement;
      posts.push({
        content_id: match[1],
        url,
        text: textOf(card || node),
      });
    });

    document.querySelectorAll("article, li, [class*='post'], [class*='dynamic'], [class*='content'], [class*='item']").forEach((node) => {
      if (!visible(node)) return;
      const text = textOf(node);
      if (text.length < 20 || text.length > 900) return;
      if (!/(\$[^$]{1,24}\([036]\d{5}\)\$|\([036]\d{5}\)|[036]\d{5})/.test(text)) return;
      posts.push({
        content_id: "",
        url: location.href,
        text,
      });
    });

    return posts.filter((post) => {
      const key = post.content_id || textKey(post.text || "");
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  async function push() {
    const posts = extractPosts();
    if (!posts.length) {
      console.log("[同花顺新帖提醒] 当前页面暂未发现可推送帖子，试试滚动一下首页或打开一条帖子详情");
      return;
    }
    const body = JSON.stringify({ source: SOURCE, posts });
    if (navigator.sendBeacon) {
      const ok = navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "text/plain" }));
      if (ok) {
        console.log(`[同花顺新帖提醒] 已推送 ${posts.length} 条到本地模拟盘`);
        return;
      }
    }
    await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "text/plain" },
      body,
    });
    console.log(`[同花顺新帖提醒] 已推送 ${posts.length} 条到本地模拟盘`);
  }

  push();
  window.__thsBloggerPushTimer && clearInterval(window.__thsBloggerPushTimer);
  window.__thsBloggerPushTimer = setInterval(push, 30000);
  console.log("[同花顺新帖提醒] 已启动：每 30 秒检查当前页面可见帖子。保持这个页面打开即可。");
})();
