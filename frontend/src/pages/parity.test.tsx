import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DocumentsPage } from "./DocumentsPage";
import { TutorPage } from "./TutorPage";
import { WorkspacePage } from "./WorkspacePage";

vi.mock("@monaco-editor/react", () => ({ default: () => <div data-testid="monaco-editor"/> }));
vi.mock("../api/client", () => ({
  api: {
    documents: vi.fn().mockResolvedValue([]),
    upload: vi.fn(), addYouTube: vi.fn(), deleteDocument: vi.fn(),
    ingestionJob: vi.fn(), cancelIngestion: vi.fn(), tutor: vi.fn(), hint: vi.fn(),
    executeProject: vi.fn(), executionJob: vi.fn(), cancelExecution: vi.fn(),
  },
  errorMessage: (error: unknown) => error instanceof Error ? error.message : "Error",
}));

function renderPage(page: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{page}</QueryClientProvider>);
}

describe("React parity controls", () => {
  beforeEach(() => vi.clearAllMocks());

  it("supports multi-file upload and transcript language preferences", async () => {
    const { container } = renderPage(<DocumentsPage/>);
    expect(await screen.findByText("No resources yet")).toBeInTheDocument();
    expect(container.querySelector<HTMLInputElement>('input[type="file"]')?.multiple).toBe(true);
    expect(screen.getByLabelText("Preferred transcript languages")).toHaveValue("en");
  });

  it("provides a standalone progressive-hint problem editor", async () => {
    renderPage(<TutorPage/>);
    expect(await screen.findByLabelText("Need a hint instead?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reveal hint 1" })).toBeDisabled();
  });

  it("provides entry-point, test, reset, and Monaco controls", () => {
    renderPage(<WorkspacePage/>);
    expect(screen.getByLabelText("Entry point")).toHaveValue("main.py");
    expect(screen.getByLabelText("Run configured tests")).toBeChecked();
    expect(screen.getByRole("button", { name: "Reset" })).toBeInTheDocument();
    expect(screen.getByTestId("monaco-editor")).toBeInTheDocument();
  });
});
