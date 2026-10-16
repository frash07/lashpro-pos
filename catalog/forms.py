from django import forms


class ProductImportUploadForm(forms.Form):
    file = forms.FileField(
        label="Product file",
        help_text="Choose a UTF-8 CSV or .xlsx workbook (maximum 5 MB).",
    )

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        extension = uploaded_file.name.rsplit(".", 1)[-1].casefold() if "." in uploaded_file.name else ""
        if extension not in {"csv", "xlsx"}:
            raise forms.ValidationError("Choose a .csv or .xlsx file.")
        if uploaded_file.size > 5 * 1024 * 1024:
            raise forms.ValidationError("The file is too large. Maximum upload size is 5 MB.")
        return uploaded_file
