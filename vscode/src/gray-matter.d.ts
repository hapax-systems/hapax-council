declare module "gray-matter" {
  interface GrayMatterFile {
    data: Record<string, unknown>;
    content: string;
    orig: string;
  }
  function matter(input: string): GrayMatterFile;
  namespace matter {
    function stringify(content: string, data: Record<string, unknown>): string;
  }
  export = matter;
}
