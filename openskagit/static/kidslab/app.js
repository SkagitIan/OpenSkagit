(function () {
  const dataElement = document.getElementById("kidslab-cards");
  const cards = dataElement ? JSON.parse(dataElement.textContent || "[]") : [];
  const cardStack = document.getElementById("card-stack");
  const swipeLayer = document.getElementById("swipe-layer");
  const emptyState = document.getElementById("kidslab-empty-state");

  const animationPresets = {
    up: { enter: "translateY(120%)", exit: "translateY(-120%)" },
    down: { enter: "translateY(-120%)", exit: "translateY(120%)" },
    left: { enter: "translateX(120%)", exit: "translateX(-120%)" },
    right: { enter: "translateX(-120%)", exit: "translateX(120%)" },
  };

  const typeBackgrounds = {
    YOUTUBE: "#fb7185",
    ANIMAL_SOUND: "#a855f7",
    PHOTO: "#22c55e",
    DRAW: "#f97316",
    PLACEHOLDER: "#6366f1",
    MAZE: "#0f172a",
  };

  if (!cards.length) {
    if (emptyState) {
      emptyState.style.display = "flex";
    }
    return;
  }

  if (emptyState) {
    emptyState.style.display = "none";
  }

  const arrowDefs = {
    up: { colors: ["#fb7185", "#ef4444"], cheeks: "#fdba74", faceY: 64 },
    down: { colors: ["#22c55e", "#16a34a"], cheeks: "#fbbf24", faceY: 86 },
    left: { colors: ["#38bdf8", "#0ea5e9"], cheeks: "#f472b6", faceX: 52 },
    right: { colors: ["#facc15", "#f97316"], cheeks: "#fbbf24", faceX: 88 },
  };

  const arrowPaths = {
    up: "M70 8 L124 62 C128 66 125 74 118 74 H98 V125 C98 131 93 136 87 136 H53 C47 136 42 131 42 125 V74 H22 C15 74 12 66 16 62 Z",
    down: "M70 132 L16 78 C12 74 15 66 22 66 H42 V15 C42 9 47 4 53 4 H87 C93 4 98 9 98 15 V66 H118 C125 66 128 74 124 78 Z",
    left: "M8 70 L62 16 C66 12 74 15 74 22 V42 H125 C131 42 136 47 136 53 V87 C136 93 131 98 125 98 H74 V118 C74 125 66 128 62 124 Z",
    right: "M132 70 L78 124 C74 128 66 125 66 118 V98 H15 C9 98 4 93 4 87 V53 C4 47 9 42 15 42 H66 V22 C66 15 74 12 78 16 Z",
  };

  const arrowSvgs = Object.fromEntries(
    Object.entries(arrowDefs).map(([direction, config]) => [
      direction,
      buildArrowSvg(direction, config),
    ])
  );

  function buildArrowSvg(direction, config) {
    const gradId = `arrow-${direction}-grad`;
    const { colors, cheeks } = config;
    const faceX = config.faceX || 70;
    const faceY = config.faceY || 70;
    return `
      <svg class="edge-arrow-svg" viewBox="0 0 140 140" aria-hidden="true" focusable="false">
        <defs>
          <linearGradient id="${gradId}" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="${colors[0]}"/>
            <stop offset="100%" stop-color="${colors[1]}"/>
          </linearGradient>
        </defs>
        <path d="${arrowPaths[direction]}" fill="url(#${gradId})" stroke="rgba(15,23,42,0.3)" stroke-width="4" stroke-linejoin="round"/>
        <path d="M40 36 Q50 20 70 20" stroke="rgba(255,255,255,0.7)" stroke-width="6" stroke-linecap="round" fill="none"/>
        <circle cx="${faceX - 12}" cy="${faceY}" r="6" fill="${cheeks}"/>
        <circle cx="${faceX + 12}" cy="${faceY}" r="6" fill="${cheeks}"/>
        <path d="M${faceX - 22} ${faceY - 6} q6 8 12 0" stroke="#1f2937" stroke-width="4" stroke-linecap="round" fill="none"/>
        <path d="M${faceX + 10} ${faceY - 6} q6 8 12 0" stroke="#1f2937" stroke-width="4" stroke-linecap="round" fill="none"/>
        <path d="M${faceX - 6} ${faceY + 8} q6 8 12 0" stroke="#1f2937" stroke-width="4" stroke-linecap="round" fill="none"/>
      </svg>
    `;
  }

  const cardHooks = new Map();
  const directionIndexes = new Map();
  const startIndex = Math.floor(Math.random() * cards.length);

  const renderers = {
    YOUTUBE: renderYouTubeCard,
    ANIMAL_SOUND: renderAnimalSoundCard,
    PHOTO: renderPhotoCard,
    DRAW: renderDrawCard,
    PLACEHOLDER: renderPlaceholderCard,
    MAZE: renderDrawCard,
  };

  const cardEntries = cards.map((card, index) => {
    const element = document.createElement("article");
    element.className = "card";
    element.dataset.cardType = card.type;
    element.dataset.visible = "false";
    const normalizedDirection = (card.direction || "right").toLowerCase();
    element.dataset.direction = normalizedDirection;

    const backgroundColor =
      card.config?.background || typeBackgrounds[card.type] || "#1f2937";
    element.style.setProperty("--card-bg", backgroundColor);

    if (normalizedDirection && !directionIndexes.has(normalizedDirection)) {
      directionIndexes.set(normalizedDirection, index);
    }

    const renderer = renderers[card.type] || renderPlaceholderCard;
    const hooks = renderer(element, card) || {};
    cardHooks.set(card.id, hooks);

    cardStack.appendChild(element);
    return { card, element };
  });

  let currentIndex = startIndex;
  let currentDirection = (cardEntries[startIndex]?.card.direction || "right").toLowerCase();
  let isTransitioning = false;
  let pointerStart = null;
  let swipeLockCount = 0;

  const lockSwipe = () => {
    swipeLockCount += 1;
  };

  const unlockSwipe = () => {
    swipeLockCount = Math.max(0, swipeLockCount - 1);
  };

  const swipeLocked = () => swipeLockCount > 0;

  function showInitialCard() {
    const initial = cardEntries[startIndex];
    if (!initial) {
      return;
    }
    const element = initial.element;
    element.dataset.visible = "true";
    element.style.transform = "translate(0, 0)";
    currentDirection = (initial.card.direction || "right").toLowerCase();
    cardHooks.get(initial.card.id)?.onShow?.();
  }

  function clampIndex(index) {
    if (!cardEntries.length) {
      return 0;
    }
    return (index + cardEntries.length) % cardEntries.length;
  }

  function setActiveCard(targetIndex, direction) {
    if (isTransitioning || targetIndex === currentIndex) {
      return;
    }

    const clampedIndex = clampIndex(targetIndex);
    const targetEntry = cardEntries[clampedIndex];
    if (!targetEntry) {
      return;
    }

    const currentEntry = cardEntries[currentIndex];
    const targetCard = targetEntry.element;
    const currentCard = currentEntry?.element;
    const preset = animationPresets[direction] || animationPresets.right;

    isTransitioning = true;
    targetCard.dataset.visible = "true";
    targetCard.style.transform = preset.enter;
    cardHooks.get(targetEntry.card.id)?.onShow?.();

    requestAnimationFrame(() => {
      targetCard.style.transform = "translate(0, 0)";
      if (currentCard) {
        currentCard.style.transform = preset.exit;
        cardHooks.get(currentEntry.card.id)?.onHide?.();
      }
    });

    setTimeout(() => {
      if (currentCard) {
        currentCard.dataset.visible = "false";
        currentCard.style.transform = "translate(0, 0)";
      }
      currentIndex = clampedIndex;
      currentDirection = direction;
      isTransitioning = false;
    }, 420);
  }

  function goToCard(direction) {
    if (!cardEntries.length) {
      return;
    }
    const normalized = (direction || "right").toLowerCase();
    const mappedIndex = directionIndexes.get(normalized);
    if (typeof mappedIndex === "number") {
      setActiveCard(mappedIndex, normalized);
      return;
    }
    const delta = normalized === "left" || normalized === "up" ? -1 : 1;
    setActiveCard(currentIndex + delta, normalized);
  }

  function handlePointerStart(event) {
    if (swipeLocked()) {
      return;
    }
    pointerStart = { x: event.clientX, y: event.clientY };
    swipeLayer.setPointerCapture?.(event.pointerId);
  }

  function handlePointerEnd(event) {
    if (swipeLocked()) {
      pointerStart = null;
      return;
    }
    if (!pointerStart) {
      return;
    }

    const deltaX = event.clientX - pointerStart.x;
    const deltaY = event.clientY - pointerStart.y;
    const threshold = 40;

    swipeLayer.releasePointerCapture?.(event.pointerId);

    if (Math.abs(deltaX) < threshold && Math.abs(deltaY) < threshold) {
      pointerStart = null;
      return;
    }

    const direction =
      Math.abs(deltaX) > Math.abs(deltaY)
        ? deltaX > 0
          ? "right"
          : "left"
        : deltaY > 0
        ? "down"
        : "up";

    goToCard(direction);
    pointerStart = null;
  }

  function handlePointerCancel() {
    pointerStart = null;
  }

  showInitialCard();
  swipeLayer.addEventListener("pointerdown", handlePointerStart);
  swipeLayer.addEventListener("pointerup", handlePointerEnd);
  swipeLayer.addEventListener("pointercancel", handlePointerCancel);

  document.addEventListener("keydown", (event) => {
    const keyMap = {
      ArrowUp: "up",
      ArrowDown: "down",
      ArrowLeft: "left",
      ArrowRight: "right",
    };
    const direction = keyMap[event.key];
    if (direction) {
      event.preventDefault();
      goToCard(direction);
    }
  });

  document.querySelectorAll(".kidslab-edge-buttons button").forEach((button) => {
    const direction = button.dataset.direction;
    const svgMarkup = arrowSvgs[direction] || "";
    button.innerHTML = `<span class="sr-only">Go ${direction}</span>${svgMarkup}`;
    button.setAttribute("aria-label", `Go ${direction}`);

    const handleNavigate = (event) => {
      event.preventDefault();
      event.stopPropagation();
      goToCard(direction);
    };
    button.addEventListener("pointerdown", (event) => event.stopPropagation());
    button.addEventListener("pointerup", handleNavigate);
    button.addEventListener("click", handleNavigate);
  });

  function createHeader(card) {
    const header = document.createElement("div");
    header.className = "card-title";
    header.textContent = card.title;
    return header;
  }

  function renderYouTubeCard(element, card) {
    const header = createHeader(card);
    element.appendChild(header);

    const container = document.createElement("div");
    container.className = "card-media card-video";
    const iframe = document.createElement("iframe");
    iframe.allow = "autoplay; fullscreen";
    iframe.allowFullscreen = true;
    iframe.loading = "lazy";
    iframe.src = buildEmbedUrl(card.assets.youtube_url);
    iframe.title = card.title;

    container.appendChild(iframe);
    element.appendChild(container);

    return {
      onHide() {
        iframe.src = iframe.src;
      },
    };
  }

  function renderAnimalSoundCard(element, card) {
    const srTitle = document.createElement("span");
    srTitle.className = "sr-only";
    srTitle.textContent = card.title;
    element.appendChild(srTitle);

    const media = document.createElement("div");
    media.className = "card-media";
    const img = document.createElement("img");
    img.className = "card-image";
    img.alt = card.title;
    img.src = card.assets.image || card.assets.photo || "";
    media.appendChild(img);
    element.appendChild(media);

    const audio = new Audio(card.assets.audio || "");
    audio.preload = "auto";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "card-sound-button";
    const randomTop = 20 + Math.random() * 60;
    const randomLeft = 20 + Math.random() * 60;
    button.style.top = `${randomTop}%`;
    button.style.left = `${randomLeft}%`;

    const icon = document.createElement("span");
    icon.className = "sound-play-icon";
    icon.innerHTML = `
      <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
        <circle cx="32" cy="32" r="28" fill="rgba(255,255,255,0.2)" />
        <path d="M26 20 L46 32 L26 44 Z" fill="#fff" stroke="#0f172a" stroke-width="2" stroke-linejoin="round"/>
      </svg>
    `;
    button.appendChild(icon);

    const srLabel = document.createElement("span");
    srLabel.className = "sr-only";
    srLabel.textContent = `Play ${card.title}`;
    button.appendChild(srLabel);

    const indicator = document.createElement("span");
    indicator.className = "card-audio-indicator";
    button.appendChild(indicator);

    button.addEventListener("click", () => {
      button.classList.add("is-bouncing");
      setTimeout(() => button.classList.remove("is-bouncing"), 600);
      if (!card.assets.audio) {
        return;
      }
      audio.currentTime = 0;
      audio.play();
    });

    media.appendChild(button);

    audio.addEventListener("play", () => indicator.classList.add("is-playing"));
    ["pause", "ended"].forEach((eventName) => {
      audio.addEventListener(eventName, () =>
        indicator.classList.remove("is-playing")
      );
    });

    return {
      onHide() {
        audio.pause();
        audio.currentTime = 0;
        indicator.classList.remove("is-playing");
      },
    };
  }

  function renderPhotoCard(element, card) {
    const srOnly = document.createElement("span");
    srOnly.className = "sr-only";
    srOnly.textContent = card.title;
    element.appendChild(srOnly);

    if (card.assets.photo || card.assets.image) {
      const media = document.createElement("div");
      media.className = "card-media";
      const img = document.createElement("img");
      img.className = "card-image";
      img.alt = card.title;
      img.src = card.assets.photo || card.assets.image;
      media.appendChild(img);
      element.appendChild(media);
    }

    return {};
  }

  function renderDrawCard(element, card) {
    const showTitle = !["PHOTO", "ANIMAL_SOUND", "MAZE"].includes(card.type);
    if (showTitle) {
      const header = createHeader(card);
      element.appendChild(header);
    } else {
      const sr = document.createElement("span");
      sr.className = "sr-only";
      sr.textContent = card.title;
      element.appendChild(sr);
    }

    const hasBackgroundImage =
      card.type === "MAZE" || Boolean(card.assets.photo || card.assets.image);

    const wrapper = document.createElement("div");
    wrapper.className = hasBackgroundImage ? "card-maze-wrapper" : "card-draw-wrapper";
    const canvas = document.createElement("canvas");
    canvas.className = hasBackgroundImage ? "card-maze-canvas" : "card-canvas";
    canvas.setAttribute("touch-action", "none");

    if (hasBackgroundImage) {
      const backgroundImage = document.createElement("img");
      backgroundImage.className = "card-maze-image";
      backgroundImage.alt = card.title;
      backgroundImage.src = card.assets.photo || card.assets.image || "";
      wrapper.appendChild(backgroundImage);
    }

    wrapper.appendChild(canvas);
    element.appendChild(wrapper);

    const toolbar = document.createElement("div");
    const useFloatingToolbar = hasBackgroundImage;
    toolbar.className = useFloatingToolbar ? "card-maze-toolbar" : "card-draw-toolbar";
    const clearButton = document.createElement("button");
    clearButton.type = "button";
    clearButton.className = hasBackgroundImage ? "card-button card-maze-clear" : "card-button";
    clearButton.textContent = hasBackgroundImage ? "Clear Path" : "Clear";
    toolbar.appendChild(clearButton);
    if (useFloatingToolbar) {
      wrapper.appendChild(toolbar);
    } else {
      element.appendChild(toolbar);
    }

    const ctx = canvas.getContext("2d");
    ctx.strokeStyle = hasBackgroundImage ? "#facc15" : "#f8fafc";
    ctx.lineWidth = hasBackgroundImage ? 10 : 6;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";

    let drawing = false;

    function resizeCanvas() {
      const scale = window.devicePixelRatio || 1;
      canvas.width = canvas.clientWidth * scale;
      canvas.height = canvas.clientHeight * scale;
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
    }

    function getRelative(event) {
      const rect = canvas.getBoundingClientRect();
      return {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      };
    }

    function pointerDown(event) {
      event.preventDefault();
      event.stopPropagation();
      if (!drawing) {
        lockSwipe();
      }
      drawing = true;
      ctx.beginPath();
      const { x, y } = getRelative(event);
      ctx.moveTo(x, y);
      canvas.setPointerCapture?.(event.pointerId);
    }

    function pointerMove(event) {
      if (!drawing) {
        return;
      }
      event.stopPropagation();
      const { x, y } = getRelative(event);
      ctx.lineTo(x, y);
      ctx.stroke();
    }

    function pointerUp(event) {
      if (drawing) {
        unlockSwipe();
      }
      drawing = false;
      event.stopPropagation?.();
      canvas.releasePointerCapture?.(event?.pointerId);
    }

    function clearCanvas(event) {
      event?.preventDefault?.();
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.beginPath();
    }

    window.addEventListener("resize", resizeCanvas);
    resizeCanvas();

    canvas.addEventListener("pointerdown", pointerDown);
    canvas.addEventListener("pointermove", pointerMove);
    canvas.addEventListener("pointerup", pointerUp);
    canvas.addEventListener("pointerleave", pointerUp);
    clearButton.addEventListener("click", clearCanvas);

    return {
      onShow() {
        resizeCanvas();
      },
      onHide() {
        drawing = false;
        unlockSwipe();
      },
      cleanup() {
        window.removeEventListener("resize", resizeCanvas);
        canvas.removeEventListener("pointerdown", pointerDown);
        canvas.removeEventListener("pointermove", pointerMove);
        canvas.removeEventListener("pointerup", pointerUp);
        canvas.removeEventListener("pointerleave", pointerUp);
        clearButton.removeEventListener("click", clearCanvas);
      },
    };
  }

  function renderPlaceholderCard(element, card) {
    const header = createHeader(card);
    element.appendChild(header);
    const prompt = document.createElement("p");
    prompt.className = "card-prompt";
    prompt.textContent = card.config?.description || card.title;
    element.appendChild(prompt);
    return {};
  }

  function buildEmbedUrl(rawUrl) {
    if (!rawUrl) {
      return "";
    }

    try {
      const url = new URL(rawUrl);
      let videoId = null;

      if (url.hostname.includes("youtu.be")) {
        videoId = url.pathname.slice(1);
      } else if (url.hostname.includes("youtube.com")) {
        videoId = url.searchParams.get("v");
      }

      if (!videoId) {
        videoId = rawUrl;
      }

      return `https://www.youtube.com/embed/${videoId}?autoplay=1&loop=1&playlist=${videoId}&controls=0&rel=0&mute=1&modestbranding=1&playsinline=1`;
    } catch (error) {
      return rawUrl;
    }
  }
})();
