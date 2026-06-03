import React from "react";
import ReactDOM from "react-dom/client";
import { InventoryApp } from "./InventoryApp";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <InventoryApp />
  </React.StrictMode>,
);
