import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryResult } from "../QueryResult";

// Mock react-markdown to avoid ESM/bundler issues in tests
vi.mock("react-markdown", () => ({
  default: ({ children }: { children: string }) => (
    <div data-testid="markdown-content">{children}</div>
  ),
}));

// Mock remark-gfm
vi.mock("remark-gfm", () => ({ default: () => {} }));

// Mock the lazy-loaded MermaidBlock
vi.mock("../MermaidBlock", () => ({
  MermaidBlock: ({ source }: { source: string }) => (
    <div data-testid="mermaid-block">{source}</div>
  ),
}));

const defaultMetadata = {
  agent_used: "dev_story",
  tokens_in: 500,
  tokens_out: 300,
  elapsed_ms: 2400,
};

describe("QueryResult", () => {
  it("renders the query text", () => {
    render(
      <QueryResult
        query="What is the system architecture?"
        markdown=""
        isStreaming={false}
      />,
    );

    expect(
      screen.getByText("What is the system architecture?"),
    ).toBeInTheDocument();
  });

  it("renders markdown content when provided", () => {
    render(
      <QueryResult
        query="test query"
        markdown="# Hello\n\nSome content here."
        isStreaming={false}
      />,
    );

    const markdownEl = screen.getByTestId("markdown-content");
    expect(markdownEl).toBeInTheDocument();
    expect(markdownEl).toHaveTextContent("# Hello");
  });

  it("does not render markdown container when markdown is empty", () => {
    render(
      <QueryResult query="test query" markdown="" isStreaming={false} />,
    );

    expect(screen.queryByTestId("markdown-content")).not.toBeInTheDocument();
  });

  it("shows loading indicator when streaming", () => {
    render(
      <QueryResult query="test query" markdown="" isStreaming={true} />,
    );

    expect(screen.getByText("Querying...")).toBeInTheDocument();
  });

  it("does not show loading indicator when not streaming", () => {
    render(
      <QueryResult query="test query" markdown="" isStreaming={false} />,
    );

    expect(screen.queryByText("Querying...")).not.toBeInTheDocument();
  });

  it("shows agent type badge from metadata", () => {
    render(
      <QueryResult
        query="test query"
        markdown="some content"
        isStreaming={false}
        metadata={defaultMetadata}
      />,
    );

    expect(screen.getByText("dev_story")).toBeInTheDocument();
  });

  it("shows elapsed time formatted in seconds", () => {
    render(
      <QueryResult
        query="test query"
        markdown="some content"
        isStreaming={false}
        metadata={defaultMetadata}
      />,
    );

    // 2400ms → 2.4s
    expect(screen.getByText("2.4s")).toBeInTheDocument();
  });

  it("shows token count formatted in thousands", () => {
    render(
      <QueryResult
        query="test query"
        markdown="some content"
        isStreaming={false}
        metadata={defaultMetadata}
      />,
    );

    // (500 + 300) / 1000 = 0.8 → rounds to "1k tokens"
    expect(screen.getByText(/tokens/)).toBeInTheDocument();
  });

  it("does not show metadata section when metadata is absent and not streaming", () => {
    render(
      <QueryResult
        query="test query"
        markdown="some content"
        isStreaming={false}
      />,
    );

    // No agent name, no timing
    expect(screen.queryByText("dev_story")).not.toBeInTheDocument();
    expect(screen.queryByText("Querying...")).not.toBeInTheDocument();
  });

  it("handles empty markdown without crashing", () => {
    expect(() =>
      render(
        <QueryResult query="test query" markdown="" isStreaming={false} />,
      ),
    ).not.toThrow();
  });

  it("shows query prefixed with Q: label", () => {
    render(
      <QueryResult
        query="My question here"
        markdown=""
        isStreaming={false}
      />,
    );

    expect(screen.getByText("Q:")).toBeInTheDocument();
    expect(screen.getByText("My question here")).toBeInTheDocument();
  });
});
