import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App";

describe("application routing", () => {
  beforeEach(() => {
    sessionStorage.clear();
    window.history.pushState({}, "", "/login");
  });

  it("renders the sign-in experience for an unauthenticated student", () => {
    render(<App/>);
    expect(screen.getByRole("heading", { name: "Sign in to your classroom" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });
});
