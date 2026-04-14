import "@testing-library/jest-dom";

// Polyfills for react-pdf in jsdom
if (typeof window !== "undefined") {
  if (!window.DOMMatrix) {
    window.DOMMatrix = class DOMMatrix {
      constructor() {}
    };
  }
}

