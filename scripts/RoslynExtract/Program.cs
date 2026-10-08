using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

var reposRoot = Path.GetFullPath(args[0]);
var outPath = args[1];
var testAttr = new Regex(@"^(Fact|Theory|Test|TestCase|TestCaseSource|TestMethod|DataTestMethod|\w*Fact|\w*Theory)$");
var sep = Path.DirectorySeparatorChar;
const int MaxCandidates = 3, MaxHelpers = 5;

static bool IsTok(SyntaxToken t) => t.IsKind(SyntaxKind.IdentifierToken) || SyntaxFacts.IsKeywordKind(t.Kind()) || SyntaxFacts.IsContextualKeyword(t.Kind());
static bool InAttr(SyntaxToken t) => t.Parent != null && t.Parent.AncestorsAndSelf().Any(a => a is AttributeListSyntax);
static string Toks(MethodDeclarationSyntax m, bool noAttr) =>
    string.Join(" ", m.DescendantTokens().Where(t => IsTok(t) && (!noAttr || !InAttr(t))).Select(t => t.Text));

IEnumerable<string> CsFiles(string dir) => Directory.EnumerateFiles(dir, "*.cs", SearchOption.AllDirectories)
    .Where(f => !f.Contains($"{sep}obj{sep}") && !f.Contains($"{sep}bin{sep}"));
SyntaxNode Parse(string f) { try { return CSharpSyntaxTree.ParseText(File.ReadAllText(f)).GetRoot(); } catch { return null; } }
bool IsTest(MethodDeclarationSyntax m) => m.AttributeLists.SelectMany(l => l.Attributes)
    .Select(a => Regex.Replace(a.Name.ToString().Split('.').Last(), "Attribute$", "")).Any(a => testAttr.IsMatch(a));
bool IsTestPath(string rel) => rel.IndexOf("test", StringComparison.OrdinalIgnoreCase) >= 0 || rel.IndexOf("spec", StringComparison.OrdinalIgnoreCase) >= 0;

using var w = new StreamWriter(outPath);
var count = 0; var withHelpers = 0;
foreach (var repoPath in Directory.EnumerateDirectories(reposRoot))
{
    var repoDir = Path.GetFileName(repoPath);

    // Passo 1: indice de metodos auxiliares (nao-teste, em caminhos de teste), nome -> tokens sem atributos
    var helpers = new Dictionary<string, List<string>>();
    foreach (var file in CsFiles(repoPath))
    {
        var rel0 = Path.GetRelativePath(reposRoot, file);
        if (!IsTestPath(rel0)) continue;
        var r0 = Parse(file); if (r0 == null) continue;
        foreach (var m in r0.DescendantNodes().OfType<MethodDeclarationSyntax>())
        {
            if (IsTest(m) || (m.Body == null && m.ExpressionBody == null)) continue;
            if (!helpers.TryGetValue(m.Identifier.Text, out var lst)) helpers[m.Identifier.Text] = lst = new List<string>();
            if (lst.Count <= MaxCandidates) lst.Add(Toks(m, true));
        }
    }

    // Passo 2: emissao
    foreach (var file in CsFiles(repoPath))
    {
        var rel = Path.GetRelativePath(reposRoot, file);
        var root = Parse(file); if (root == null) continue;
        foreach (var t in root.DescendantNodes().OfType<TypeDeclarationSyntax>())
        {
            var tns = string.Join(".", t.Ancestors().OfType<BaseNamespaceDeclarationSyntax>().Select(n => n.Name.ToString()).Reverse());
            var chain = string.Join("+", t.AncestorsAndSelf().OfType<TypeDeclarationSyntax>().Select(x => x.Identifier.Text).Reverse());
            var fq = (tns.Length > 0 ? tns + "." : "") + chain;
            var bases = t.BaseList?.Types.Select(b => Regex.Replace(b.Type.ToString(), "<.*>", "").Split('.').Last()).ToList() ?? new List<string>();
            w.WriteLine(JsonSerializer.Serialize(new { kind = "class", repo = repoDir, className = fq, bases }));
        }
        foreach (var m in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
        {
            var attrs = m.AttributeLists.SelectMany(l => l.Attributes)
                .Select(a => Regex.Replace(a.Name.ToString().Split('.').Last(), "Attribute$", "")).ToList();
            if (!attrs.Any(a => testAttr.IsMatch(a))) continue;
            var types = m.Ancestors().OfType<TypeDeclarationSyntax>().Select(t => t.Identifier.Text).Reverse().ToList();
            var ns = string.Join(".", m.Ancestors().OfType<BaseNamespaceDeclarationSyntax>().Select(n => n.Name.ToString()).Reverse());
            var cls = (ns.Length > 0 ? ns + "." : "") + string.Join("+", types);
            var tokens = Toks(m, false);
            var tokensNoAttr = Toks(m, true);

            var names = new List<string>();
            foreach (var inv in m.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                string nm = inv.Expression switch
                {
                    IdentifierNameSyntax id => id.Identifier.Text,
                    GenericNameSyntax g => g.Identifier.Text,
                    MemberAccessExpressionSyntax ma => ma.Name.Identifier.Text,
                    _ => null
                };
                if (nm != null && nm != m.Identifier.Text && !names.Contains(nm)) names.Add(nm);
            }
            var helperToks = new List<string>(); var resolved = 0;
            foreach (var nm in names)
            {
                if (resolved >= MaxHelpers) break;
                if (helpers.TryGetValue(nm, out var cand) && cand.Count > 0 && cand.Count <= MaxCandidates)
                { helperToks.AddRange(cand); resolved++; }
            }
            if (resolved > 0) withHelpers++;
            var tokensHop1 = helperToks.Count == 0 ? tokens : tokens + " " + string.Join(" ", helperToks);

            var loc = m.GetText().Lines.Count(l => l.ToString().Trim().Length > 0);
            var awaits = m.DescendantNodes().OfType<AwaitExpressionSyntax>().Count();
            var asserts = m.DescendantNodes().OfType<InvocationExpressionSyntax>()
                .Count(i => Regex.IsMatch(i.Expression.ToString(), @"\b(Assert|Should|Verify)\b"));
            w.WriteLine(JsonSerializer.Serialize(new {
                kind = "method", repo = repoDir, file = rel, className = cls, method = m.Identifier.Text, attrs, loc, awaits, asserts,
                isAsync = m.Modifiers.Any(SyntaxKind.AsyncKeyword), tokens, tokens_noattr = tokensNoAttr, tokens_hop1 = tokensHop1,
                helpers_resolved = resolved }));
            count++;
        }
    }
}
Console.WriteLine($"{count} test methods; {withHelpers} com ao menos um auxiliar resolvido");
