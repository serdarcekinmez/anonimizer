"""Writes the small golden parser fixtures. All content is invented."""

from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))

FILES: dict[str, bytes] = {
    "semicolon_decimal_comma.csv": b"id;montant;date\n1;12,5;01/02/2024\n2;7,25;15/02/2024\n3;100,00;28/02/2024\n",
    "utf16_bom.csv": "id,label\n1,été\n2,hiver\n".encode("utf-16"),
    "utf8_bom.csv": b"\xef\xbb\xbfid,label\n1,alpha\n2,beta\n",
    "cp1252_accents.csv": "ref;libellé;prix\nA1;crème brûlée;4,50\nA2;café;1,20\nA3;thé;2,00\n".encode("cp1252"),
    "pipe_delimited.txt": b"code|qty|note\nX1|4|ok\nX2|9|late\nX3|1|ok\n",
    "quoted_multiline.csv": b'id,comment,flag\n1,"line one\nline two",Y\n2,"",N\n3,"says ""hi""",Y\n',
    "headerless_numeric.csv": b"1,10.5,2024-01-01\n2,11.0,2024-01-02\n3,9.75,2024-01-03\n",
    "preamble_header.csv": b"Quarterly export\nPrepared by the finance team\nDraft\nid,amount,region\n1,10,N\n2,20,S\n3,30,E\n",
    "two_tables_blank_sep.csv": b"id,name\n1,Aba\n2,Ebo\n\n\nsku,price,stock\nK1,2.50,10\nK2,3.75,0\nK3,1.00,7\n",
    "side_by_side.csv": b"id,name,,code,label\n1,Aba,,X,First\n2,Ebo,,Y,Second\n3,Iru,,Z,Third\n",
    "blank_row_inside.csv": b"id,amount\n1,10\n2,20\n\n3,30\n4,40\n",
    "ragged.csv": b"a,b,c\n1,2,3\n4,5\n6,7,8,9\n10,11,12\n",
    "mixed_newlines.csv": b"a,b\r\n1,2\n3,4\r\n5,6\n",
    "empty.csv": b"",
    "header_only.csv": b"id,name,amount\n",
    "single_column.csv": b"value\n10\n20\nabc\n40\n",
    "tabs.tsv": b"id\tname\tscore\n1\tAba\t3.5\n2\tEbo\t4.0\n",
    "delimiter_only_rows.csv": b"id,name,amount\n1,Aba,5\n,,\n2,Ebo,6\n",
    "stray_bytes_utf8.csv": "id,name\n1,été\n2,noël\n3,façade\n4,brûlé\n5,forêt\n6,où\n7,déjà\n8,île\n9,âge\n10,cœur\n".encode() + b"11,bad\xff\n",
}


def build(target: str = HERE) -> None:
    for name, data in FILES.items():
        with open(os.path.join(target, name), "wb") as fh:
            fh.write(data)


if __name__ == "__main__":
    build()
    print(f"{len(FILES)} parser fixtures written")
