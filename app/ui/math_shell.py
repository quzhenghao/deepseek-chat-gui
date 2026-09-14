"""HTML/JS shell rendered inside every inline math/code web surface.

The chat lane is the only scroller in the application, and Chromium refuses to
composite a widget taller than the GPU texture budget, so one long answer is
painted by a stack of fixed-height *tiles*.  Every tile renders the same
document and is translated by ``-offset``, so it shows exactly the rows
``[offset, offset + height)`` of that document; stacked without gaps they form
one continuous, unlimited page.

The shell therefore only keeps the document in sync:

``setDeepSeekDocument``  replace style + frozen HTML + live tail
``setDeepSeekStream``    append newly frozen HTML and swap the live tail
``setDeepSeekOffset``    choose which slice of the document a tile shows

Revealing the newest text is animated by the host, which grows the message
viewport and fades its edge with a native gradient curtain.  Nothing inside
Chromium changes per frame, so the animation keeps display refresh rate no
matter how long the answer is.
"""

from __future__ import annotations

MATH_WEB_SHELL = r"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="stylesheet" href="katex.min.css">
  <style>
    html, body {
      box-sizing: border-box;
      width: 100%;
      height: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: transparent;
      cursor: text;
    }
    #content-root {
      box-sizing: border-box;
      width: 100%;
      min-height: 1px;
      background: transparent;
    }
    a, button, .code-copy { cursor: pointer; }
    .deepseek-stream-anchor { display: block; height: 0; margin: 0;
      padding: 0; border: none; }
  </style>
</head>
<body>
  <main id="content-root"></main>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script src="katex.min.js"></script>
  <script>
    (() => {
      const root = document.getElementById("content-root");
      const body = document.createElement("div");
      body.className = "markdown-body";
      // Frozen HTML is appended before this anchor and the live tail is kept
      // after it, so a growing answer never re-renders what is on screen.
      const tailAnchor = document.createElement("span");
      tailAnchor.className = "deepseek-stream-anchor";
      let bridge = null;
      // The text node that holds the still-growing last line of an open code
      // fence, so frozen code lines can be appended in front of it.
      let codeTailNode = null;
      // Document y where the newest update started changing pixels; tiles
      // entirely above it never have to be touched again.
      let lastChangedTop = 0;
      let reportedHeight = -1;

      window.__deepSeekLastError = null;

      const top = () => root.getBoundingClientRect().top;

      const documentHeight = () => Math.max(
        1,
        Math.ceil(body.getBoundingClientRect().height)
      );

      const changedTop = () => {
        const rect = tailAnchor.getBoundingClientRect();
        return Math.max(0, Math.floor(rect.top - top()));
      };

      const refreshOverflow = () => {
        root.querySelectorAll(".math-display-shell").forEach((shell) => {
          const overflowing = shell.scrollWidth > shell.clientWidth + 2;
          shell.classList.toggle("is-overflowing", overflowing);
          shell.setAttribute("data-overflowing", overflowing ? "true" : "false");
          shell.setAttribute("tabindex", overflowing ? "0" : "-1");
          shell.setAttribute(
            "aria-label",
            overflowing ? "数学公式，可横向滚动查看完整内容" : "数学公式"
          );
        });
        root.querySelectorAll(".math-inline").forEach((inline) => {
          const overflowing = inline.scrollWidth > inline.clientWidth + 4;
          inline.classList.toggle("is-overflowing", overflowing);
          inline.setAttribute("tabindex", overflowing ? "0" : "-1");
        });
      };

      const renderFormulas = (scope) => {
        (scope || root).querySelectorAll("[data-tex]").forEach((node) => {
          const expression = node.getAttribute("data-tex") || "";
          try {
            if (typeof katex === "undefined") {
              throw new Error("KaTeX is unavailable");
            }
            katex.render(expression, node, {
              displayMode: node.getAttribute("data-display") === "true",
              output: "htmlAndMathml",
              throwOnError: false,
              strict: "ignore",
              trust: false,
              maxSize: 12,
              maxExpand: 1000
            });
          } catch (error) {
            node.classList.add("katex-error");
            node.textContent = expression;
          }
        });
      };

      const fragment = (markup) => {
        const template = document.createElement("template");
        template.innerHTML = markup || "";
        return template.content;
      };

      const codeHost = () => {
        const block = tailAnchor.previousElementSibling;
        if (!block || !block.classList.contains("code-block")) return null;
        return block.querySelector("pre code") || null;
      };

      const appendCodeLines = (text) => {
        const host = codeHost();
        if (!host || !text) return;
        const node = document.createTextNode(text);
        if (codeTailNode && codeTailNode.parentNode === host) {
          host.insertBefore(node, codeTailNode);
        } else {
          host.appendChild(node);
        }
      };

      const setCodeTail = (text) => {
        if (!text) {
          if (codeTailNode && codeTailNode.parentNode) {
            codeTailNode.parentNode.removeChild(codeTailNode);
          }
          codeTailNode = null;
          return;
        }
        const host = codeHost();
        if (!host) return;
        if (!codeTailNode || codeTailNode.parentNode !== host) {
          codeTailNode = document.createTextNode(text);
          host.appendChild(codeTailNode);
          return;
        }
        if (codeTailNode.textContent !== text) {
          codeTailNode.textContent = text;
        }
      };

      const report = (force) => {
        const height = documentHeight();
        if (!force && height === reportedHeight) return;
        reportedHeight = height;
        if (bridge) bridge.reportLayout(height, lastChangedTop);
      };

      const snapshot = () => JSON.stringify({
        documentHeight: documentHeight(),
        changedTop: lastChangedTop,
        characters: (body.textContent || "").length
      });

      window.setDeepSeekDocument = (payload) => {
        const data = typeof payload === "string" ? JSON.parse(payload) : payload;
        root.textContent = "";
        const style = document.createElement("style");
        style.textContent = data.style || "";
        root.appendChild(style);
        root.appendChild(body);
        body.textContent = "";
        codeTailNode = null;
        body.innerHTML = data.stable || "";
        body.appendChild(tailAnchor);
        const tail = fragment(data.tail || "");
        renderFormulas(tail);
        body.appendChild(tail);
        setCodeTail(data.codeTail || "");
        renderFormulas(body);
        refreshOverflow();
        lastChangedTop = 0;
        report(true);
        requestAnimationFrame(() => {
          lastChangedTop = changedTop();
          report(true);
        });
        if (document.fonts && document.fonts.ready) {
          document.fonts.ready.then(() => report(true));
        }
        return snapshot();
      };

      window.setDeepSeekStream = (payload) => {
        const data = typeof payload === "string" ? JSON.parse(payload) : payload;
        let codeTop = null;
        if (data.code) {
          const host = codeHost();
          if (host) {
            const range = document.createRange();
            range.selectNodeContents(host);
            range.collapse(false);
            const rect = range.getBoundingClientRect();
            codeTop = Math.max(0, Math.floor(rect.top - top()));
          }
        }
        if (data.stable) {
          const stable = fragment(data.stable);
          renderFormulas(stable);
          body.insertBefore(stable, tailAnchor);
        }
        if (data.code) appendCodeLines(data.code);
        if (data.codeTail !== undefined) setCodeTail(data.codeTail || "");
        if (data.hasTail) {
          const tail = fragment(data.tail || "");
          renderFormulas(tail);
          while (tailAnchor.nextSibling) {
            body.removeChild(tailAnchor.nextSibling);
          }
          body.appendChild(tail);
        }
        const anchorTop = changedTop();
        lastChangedTop = codeTop === null ? anchorTop : Math.min(codeTop, anchorTop);
        refreshOverflow();
        report(false);
        return snapshot();
      };

      window.setDeepSeekOffset = (offset) => {
        const value = Number.isFinite(offset) ? Number(offset) : 0;
        root.style.transform = value ? "translateY(" + (-value) + "px)" : "";
        return value;
      };

      window.refreshDeepSeekLayout = () => {
        refreshOverflow();
        report(true);
        return documentHeight();
      };

      window.deepSeekDebugState = () => JSON.stringify({
        documentHeight: documentHeight(),
        changedTop: lastChangedTop,
        characters: (body.textContent || "").length,
        error: window.__deepSeekLastError
      });

      const caretAt = (x, y) => {
        const px = Math.max(0, Math.min(window.innerWidth - 1, x));
        const py = Math.max(0, Math.min(window.innerHeight - 1, y));
        if (document.caretPositionFromPoint) {
          const caret = document.caretPositionFromPoint(px, py);
          if (caret) return { node: caret.offsetNode, offset: caret.offset };
        }
        const range = document.caretRangeFromPoint(px, py);
        return range
          ? { node: range.startContainer, offset: range.startOffset }
          : null;
      };

      let dragAnchor = null;
      document.addEventListener("mousedown", (event) => {
        if (event.button !== 0 || (
          event.target instanceof Element && event.target.closest(".code-copy")
        )) return;
        dragAnchor = caretAt(event.clientX, event.clientY);
        if (!dragAnchor || !root.contains(dragAnchor.node)) return;
        if (bridge) bridge.startSelectionDrag(event.clientX, event.clientY);
      });
      document.addEventListener("mousemove", (event) => {
        if (dragAnchor && (event.buttons & 1) && bridge) {
          bridge.moveSelectionDrag(event.clientX, event.clientY);
        }
      });
      const finishSelectionDrag = () => {
        if (!dragAnchor) return;
        dragAnchor = null;
        if (bridge) bridge.finishSelectionDrag();
      };
      window.addEventListener("mouseup", finishSelectionDrag);
      window.addEventListener("blur", finishSelectionDrag);

      window.autoScrollSelection = (delta, x, y) => {
        if (!dragAnchor) return;
        const caret = caretAt(x, y);
        if (!caret || !root.contains(caret.node)) return;
        window.getSelection().setBaseAndExtent(
          dragAnchor.node, dragAnchor.offset, caret.node, caret.offset
        );
      };

      document.addEventListener("click", (event) => {
        const button = event.target instanceof Element
          ? event.target.closest(".code-copy")
          : null;
        if (!button) return;
        const block = button.closest(".code-block");
        const code = block ? block.querySelector("pre code") : null;
        if (!code || !bridge) return;
        bridge.copyText(code.textContent || "");
        button.textContent = "已复制";
        button.classList.add("is-copied");
        window.setTimeout(() => {
          button.textContent = "复制";
          button.classList.remove("is-copied");
        }, 1400);
      });

      if (typeof QWebChannel !== "undefined" && typeof qt !== "undefined") {
        new QWebChannel(qt.webChannelTransport, (channel) => {
          bridge = channel.objects.mathBridge;
          report(true);
        });
      }

      // The chat lane owns scrolling: never let a gesture inside a windowed
      // tile shift the slice it is showing.
      const lockScroll = () => {
        if (window.scrollX || window.scrollY) window.scrollTo(0, 0);
      };
      window.addEventListener("scroll", lockScroll);
      const reflow = () => requestAnimationFrame(() => {
        refreshOverflow();
        report(true);
      });
      new ResizeObserver(reflow).observe(root);
      window.addEventListener("resize", reflow);
      document.addEventListener("wheel", (event) => {
        const horizontalRegion = event.target instanceof Element
          ? event.target.closest(
              ".math-display-shell, .math-inline.is-overflowing"
            )
          : null;
        if (horizontalRegion && event.shiftKey && event.deltaY !== 0) {
          horizontalRegion.scrollLeft += event.deltaY;
          event.preventDefault();
          return;
        }
        if (!bridge || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
        bridge.scrollVertically(event.deltaY);
        event.preventDefault();
      }, { passive: false });

      // A failed update must never leave a blank surface behind silently, so
      // every entry point records what went wrong for the host to inspect.
      [
        "setDeepSeekDocument",
        "setDeepSeekStream",
        "setDeepSeekOffset",
        "refreshDeepSeekLayout"
      ].forEach((name) => {
        const original = window[name];
        window[name] = (...args) => {
          try {
            return original(...args);
          } catch (error) {
            window.__deepSeekLastError = name + ": "
              + (error && error.message ? error.message : String(error));
            return "";
          }
        };
      });
    })();
  </script>
</body>
</html>
"""
