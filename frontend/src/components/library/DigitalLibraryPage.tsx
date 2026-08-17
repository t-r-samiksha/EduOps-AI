import { useState } from "react";
import {
  Library,
  BookOpen,
  Search,
  Plus,
  ArrowDownToLine,
  Bookmark,
  Clock,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  useLibraryCatalog,
  useAddLibraryItem,
  useIssueBook,
  useReturnBook,
  useStudentLoans,
  useAllLoans,
  LibraryItem,
} from "@/api/hooks/useDigitalLibrary";
import { useAuthStore } from "@/store/authStore";

export default function DigitalLibraryPage() {
  const { user, role } = useAuthStore();
  const isLibrarianOrAdmin = role === "admin" || role === "principal" || role === "teacher";

  const [searchQuery, setSearchQuery] = useState("");
  const selectedCategory = "all";
  const [selectedType, setSelectedType] = useState<string>("all");

  const { data: catalog = [], isLoading } = useLibraryCatalog(
    selectedCategory,
    selectedType,
    searchQuery
  );

  const { data: studentLoans = [] } = useStudentLoans(
    !isLibrarianOrAdmin && user?.id ? Number(user.id) : undefined
  );
  const { data: allLoans = [] } = useAllLoans(isLibrarianOrAdmin ? "all" : undefined);

  const addItemMutation = useAddLibraryItem();
  const issueMutation = useIssueBook();
  const returnMutation = useReturnBook();

  // Add Item Modal
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newAuthor, setNewAuthor] = useState("");
  const [newIsbn, setNewIsbn] = useState("");
  const [newCategory, setNewCategory] = useState("Mathematics");
  const [newType, setNewType] = useState("book");
  const [newCopies, setNewCopies] = useState("3");

  // Issue Modal
  const [issueItem, setIssueItem] = useState<LibraryItem | null>(null);
  const [issueStudentId, setIssueStudentId] = useState("2");
  const [issueDays, setIssueDays] = useState("14");

  const handleAddItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;

    await addItemMutation.mutateAsync({
      title: newTitle,
      author: newAuthor,
      isbn: newIsbn,
      category: newCategory,
      type: newType,
      total_copies: Number(newCopies) || 1,
    });

    setIsAddOpen(false);
    setNewTitle("");
    setNewAuthor("");
  };

  const handleIssueSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!issueItem) return;

    await issueMutation.mutateAsync({
      item_id: issueItem.id,
      student_id: Number(issueStudentId),
      loan_days: Number(issueDays),
    });

    setIssueItem(null);
  };

  const handleReturn = async (loanId: number) => {
    await returnMutation.mutateAsync(loanId);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Library className="h-7 w-7 text-primary" />
            Digital Library & Resources
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isLibrarianOrAdmin
              ? "Manage catalog inventory, past papers, loan issues, and return tracking."
              : "Search catalog books, download past papers, and monitor borrowed item due dates."}
          </p>
        </div>

        {isLibrarianOrAdmin && (
          <Button
            onClick={() => setIsAddOpen(true)}
            className="flex items-center gap-1.5 shadow-sm text-xs font-medium"
          >
            <Plus className="h-4 w-4" />
            Add Item to Catalog
          </Button>
        )}
      </div>

      {/* Filter & Search Bar */}
      <div className="flex flex-col sm:flex-row items-center gap-3">
        <div className="relative flex-1 w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search books, past papers, authors, ISBN..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9 text-xs"
          />
        </div>

        <div className="flex items-center gap-2 overflow-x-auto w-full sm:w-auto">
          {["all", "book", "past_paper", "journal", "ebook"].map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setSelectedType(t)}
              className={`px-3 py-1.5 rounded-lg border text-xs font-semibold capitalize whitespace-nowrap transition-all ${
                selectedType === t
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-muted/30 text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.replace("_", " ")}
            </button>
          ))}
        </div>
      </div>

      {/* Student: My Active Loans Section */}
      {!isLibrarianOrAdmin && studentLoans.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
            <Bookmark className="h-4 w-4 text-primary" />
            My Borrowed Books ({studentLoans.length})
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {studentLoans.map((loan) => (
              <div
                key={loan.id}
                className="p-3.5 rounded-xl border bg-muted/20 flex items-center justify-between text-xs"
              >
                <div>
                  <h4 className="font-bold text-foreground line-clamp-1">{loan.item_title}</h4>
                  <div className="flex items-center gap-1 text-muted-foreground mt-1">
                    <Clock className="h-3.5 w-3.5" />
                    Due: {new Date(loan.due_date).toLocaleDateString()}
                  </div>
                </div>
                <Badge
                  variant="outline"
                  className={
                    loan.status === "overdue"
                      ? "text-red-600 bg-red-50 border-red-200"
                      : "text-emerald-700 bg-emerald-50 border-emerald-200"
                  }
                >
                  {loan.status}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Catalog Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
        {isLoading ? (
          <div className="col-span-full py-16 text-center text-muted-foreground">
            Loading library catalog...
          </div>
        ) : catalog.length === 0 ? (
          <div className="col-span-full py-16 text-center border rounded-xl bg-card">
            <BookOpen className="h-10 w-10 mx-auto text-muted-foreground/50 mb-3" />
            <h3 className="font-semibold text-foreground">No catalog items found</h3>
            <p className="text-sm text-muted-foreground mt-1">
              Try adjusting your search query or filter tags.
            </p>
          </div>
        ) : (
          catalog.map((item) => (
            <Card key={item.id} className="border shadow-xs hover:shadow-md transition-shadow">
              <CardContent className="p-4 flex flex-col justify-between h-full space-y-3">
                <div>
                  <div className="flex items-center justify-between gap-1">
                    <Badge variant="outline" className="text-[11px] capitalize">
                      {item.type.replace("_", " ")}
                    </Badge>
                    <span
                      className={`text-[11px] font-bold ${
                        item.available_copies > 0 ? "text-emerald-600" : "text-red-500"
                      }`}
                    >
                      {item.available_copies} / {item.total_copies} Available
                    </span>
                  </div>

                  <h3 className="font-bold text-sm text-foreground mt-2 line-clamp-2">
                    {item.title}
                  </h3>
                  {item.author && (
                    <p className="text-xs text-muted-foreground mt-0.5">{item.author}</p>
                  )}
                </div>

                <div className="border-t pt-2.5 flex gap-2">
                  {isLibrarianOrAdmin ? (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={item.available_copies <= 0}
                      onClick={() => setIssueItem(item)}
                      className="w-full text-xs flex items-center justify-center gap-1"
                    >
                      <Bookmark className="h-3.5 w-3.5" />
                      Issue Copy
                    </Button>
                  ) : item.file_url ? (
                    <Button
                      size="sm"
                      onClick={() => window.open(item.file_url, "_blank")}
                      className="w-full text-xs flex items-center justify-center gap-1"
                    >
                      <ArrowDownToLine className="h-3.5 w-3.5" />
                      Download PDF
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled
                      className="w-full text-xs"
                    >
                      {item.available_copies > 0 ? "In Library" : "Out on Loan"}
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* Admin: Active Loans Table */}
      {isLibrarianOrAdmin && allLoans.length > 0 && (
        <Card className="border shadow-xs mt-6 overflow-hidden">
          <CardContent className="p-0">
            <div className="p-4 border-b bg-muted/20 flex items-center justify-between">
              <h3 className="font-bold text-sm text-foreground">
                Active & Overdue Book Loans ({allLoans.length})
              </h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b bg-muted/40 font-semibold text-muted-foreground">
                    <th className="p-3">Book Title</th>
                    <th className="p-3">Borrowed By</th>
                    <th className="p-3">Issued Date</th>
                    <th className="p-3">Due Date</th>
                    <th className="p-3">Status</th>
                    <th className="p-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {allLoans.map((l) => (
                    <tr key={l.id}>
                      <td className="p-3 font-semibold text-foreground">{l.item_title}</td>
                      <td className="p-3 text-muted-foreground">{l.student_name}</td>
                      <td className="p-3 text-muted-foreground">
                        {new Date(l.issued_at).toLocaleDateString()}
                      </td>
                      <td className="p-3 font-medium">
                        {new Date(l.due_date).toLocaleDateString()}
                      </td>
                      <td className="p-3">
                        <Badge
                          variant="outline"
                          className={
                            l.status === "overdue"
                              ? "text-red-600 bg-red-50"
                              : l.status === "returned"
                              ? "text-muted-foreground"
                              : "text-emerald-700 bg-emerald-50"
                          }
                        >
                          {l.status}
                        </Badge>
                      </td>
                      <td className="p-3 text-right">
                        {l.status !== "returned" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleReturn(l.id)}
                            className="h-7 text-xs flex items-center gap-1 ml-auto"
                          >
                            <RotateCcw className="h-3 w-3" />
                            Return
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Add Item Modal */}
      <Dialog open={isAddOpen} onOpenChange={setIsAddOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Plus className="h-5 w-5 text-primary" />
              Add Library Item
            </DialogTitle>
          </DialogHeader>

          <form onSubmit={handleAddItem} className="space-y-3 mt-2">
            <div>
              <label className="text-xs font-semibold text-foreground">Title</label>
              <Input
                required
                placeholder="e.g. Modern Physics (3rd Ed)"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-foreground">Author</label>
              <Input
                placeholder="e.g. Stephen Hawking"
                value={newAuthor}
                onChange={(e) => setNewAuthor(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-foreground">ISBN (Optional)</label>
              <Input
                placeholder="e.g. 978-0-123456-47-2"
                value={newIsbn}
                onChange={(e) => setNewIsbn(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-foreground">Category</label>
                <select
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                  className="w-full mt-1 p-2 rounded-lg border bg-background text-xs"
                >
                  <option value="Mathematics">Mathematics</option>
                  <option value="Physics">Physics</option>
                  <option value="Chemistry">Chemistry</option>
                  <option value="Computer Science">Computer Science</option>
                  <option value="Literature">Literature</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold text-foreground">Format Type</label>
                <select
                  value={newType}
                  onChange={(e) => setNewType(e.target.value)}
                  className="w-full mt-1 p-2 rounded-lg border bg-background text-xs"
                >
                  <option value="book">Physical Book</option>
                  <option value="past_paper">Past Paper</option>
                  <option value="journal">Academic Journal</option>
                  <option value="ebook">E-Book (Digital)</option>
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs font-semibold text-foreground">Total Copies</label>
              <Input
                type="number"
                min={1}
                value={newCopies}
                onChange={(e) => setNewCopies(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t">
              <Button type="button" variant="ghost" onClick={() => setIsAddOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={addItemMutation.isPending}>
                {addItemMutation.isPending ? "Adding..." : "Add to Catalog"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* Issue Book Modal */}
      <Dialog open={!!issueItem} onOpenChange={() => setIssueItem(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Bookmark className="h-5 w-5 text-primary" />
              Issue Book Copy
            </DialogTitle>
          </DialogHeader>

          {issueItem && (
            <form onSubmit={handleIssueSubmit} className="space-y-3 mt-2">
              <div className="p-3 rounded-lg bg-muted/20 border text-xs">
                <span className="font-bold text-foreground">{issueItem.title}</span>
                <p className="text-muted-foreground mt-0.5">{issueItem.author}</p>
              </div>

              <div>
                <label className="text-xs font-semibold text-foreground">Student ID</label>
                <Input
                  type="number"
                  required
                  value={issueStudentId}
                  onChange={(e) => setIssueStudentId(e.target.value)}
                  className="mt-1 text-xs"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-foreground">Loan Duration (Days)</label>
                <Input
                  type="number"
                  min={1}
                  required
                  value={issueDays}
                  onChange={(e) => setIssueDays(e.target.value)}
                  className="mt-1 text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t">
                <Button type="button" variant="ghost" onClick={() => setIssueItem(null)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={issueMutation.isPending}>
                  {issueMutation.isPending ? "Issuing..." : "Confirm Issue"}
                </Button>
              </div>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
