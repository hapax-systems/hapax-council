import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { QueryInput } from "../QueryInput";

describe("QueryInput", () => {
  it("submits on Enter key with non-empty input", async () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "what is the system architecture");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    expect(onSubmit).toHaveBeenCalledWith("what is the system architecture");
  });

  it("does not submit on Enter when input is empty", () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not submit on Shift+Enter (allows newline)", async () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "multi line query");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submit button is disabled when input is empty", () => {
    render(<QueryInput onSubmit={vi.fn()} isLoading={false} />);

    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
  });

  it("submit button is enabled when input has content", async () => {
    render(<QueryInput onSubmit={vi.fn()} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "a question");

    const button = screen.getByRole("button");
    expect(button).not.toBeDisabled();
  });

  it("disables textarea during loading", () => {
    render(<QueryInput onSubmit={vi.fn()} isLoading={true} />);

    const textarea = screen.getByRole("textbox");
    expect(textarea).toBeDisabled();
  });

  it("disables submit button during loading", () => {
    render(<QueryInput onSubmit={vi.fn()} isLoading={true} />);

    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
  });

  it("clears input after submit via button click", async () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "my query");

    const button = screen.getByRole("button");
    fireEvent.click(button);

    expect(textarea).toHaveValue("");
    expect(onSubmit).toHaveBeenCalledWith("my query");
  });

  it("clears input after submit via Enter key", async () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "my query");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    expect(textarea).toHaveValue("");
  });

  it("trims whitespace before submitting", async () => {
    const onSubmit = vi.fn();
    render(<QueryInput onSubmit={onSubmit} isLoading={false} />);

    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "  spaced query  ");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });

    expect(onSubmit).toHaveBeenCalledWith("spaced query");
  });

  it("renders custom placeholder when provided", () => {
    render(
      <QueryInput
        onSubmit={vi.fn()}
        isLoading={false}
        placeholder="Custom placeholder text"
      />,
    );

    const textarea = screen.getByPlaceholderText("Custom placeholder text");
    expect(textarea).toBeInTheDocument();
  });

  it("renders default placeholder when none provided", () => {
    render(<QueryInput onSubmit={vi.fn()} isLoading={false} />);

    const textarea = screen.getByPlaceholderText(
      "Ask about development history, system patterns, architecture...",
    );
    expect(textarea).toBeInTheDocument();
  });
});
